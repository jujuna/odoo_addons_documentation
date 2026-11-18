# The fixes of the second review of the field guard, the views and the profile groups: one test per item.
import base64
import hashlib
import io
import json
from datetime import date

from lxml import etree
from PIL import Image

from odoo import Command
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger


class GuardCase(HttpCase):
    """ A user whose client calls go through /web/dataset/call_kw, like the web client's own. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = 'gec-access-manager-codex-pw'
        cls.Fields = cls.env['ir.model.fields']

    @classmethod
    def _field_line(cls, model_name, field_name, mode, **values):
        return Command.create({
            'model_id': cls.env['ir.model']._get(model_name).id,
            'field_id': cls.Fields._get(model_name, field_name).id,
            'mode': mode, **values,
        })

    def _call(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })


@tagged('post_install', '-at_install')
class TestSaveGuard(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_save_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        Partner = cls.env['res.partner']
        cls.plain = Partner.create({'name': 'Plain', 'ref': 'plain', 'function': 'F0',
                                    'website': 'plain.example.com', 'email': 'plain@example.com', 'phone': '1'})
        cls.locked = Partner.create({'name': 'Locked', 'ref': 'locked', 'function': 'F0', 'phone': '1'})
        cls.vip = Partner.create({'name': 'Vip', 'ref': 'vip', 'website': 'vip.example.com'})
        cls.be, cls.de = cls.env.ref('base.be'), cls.env.ref('base.de')
        cls.profile = cls.env['gec.access.profile'].create({
            'name': 'Codex save',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [
                cls._field_line('res.partner', 'phone', 'readonly'),
                cls._field_line('res.partner', 'email', 'hide'),
                cls._field_line('res.partner', 'function', 'readonly', condition="ref == 'locked'"),
                cls._field_line('res.partner', 'website', 'hide', condition="ref == 'vip'"),
                cls._field_line('res.partner', 'country_id', 'keep',
                                field_domain=repr([('id', 'in', cls.be.ids)])),
            ],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _multi(self, records, vals_list, specification=None):
        return self._call('res.partner', 'web_save_multi', [records.ids, vals_list],
                          {'specification': specification or {}})

    def test_web_save_multi_drops_a_read_only_field(self):
        self._multi(self.plain | self.locked, [{'name': 'N1', 'phone': '999'}, {'name': 'N2', 'phone': '999'}])
        (self.plain | self.locked).invalidate_recordset()
        self.assertEqual((self.plain.name, self.locked.name), ('N1', 'N2'))
        self.assertEqual((self.plain.phone, self.locked.phone), ('1', '1'))

    def test_web_save_multi_drops_a_hidden_field(self):
        self._multi(self.plain, [{'name': 'N3', 'email': 'changed@example.com'}])
        self.plain.invalidate_recordset()
        self.assertEqual(self.plain.name, 'N3')
        self.assertEqual(self.plain.email, 'plain@example.com')

    def test_web_save_multi_drops_a_field_locked_under_a_condition_per_record(self):
        self._multi(self.plain | self.locked, [{'function': 'F1'}, {'function': 'F1'}])
        (self.plain | self.locked).invalidate_recordset()
        self.assertEqual((self.plain.function, self.locked.function), ('F1', 'F0'))

    @mute_logger('odoo.http')
    def test_web_save_multi_refuses_a_value_outside_the_filter(self):
        with self.assertRaises(JsonRpcException):
            self._multi(self.plain, [{'country_id': self.de.id}])
        self.plain.invalidate_recordset()
        self.assertFalse(self.plain.country_id)
        self._multi(self.plain, [{'country_id': self.be.id}])
        self.plain.invalidate_recordset()
        self.assertEqual(self.plain.country_id, self.be)

    def test_web_save_multi_blanks_a_conditionally_hidden_field_on_read_back(self):
        result = self._multi(self.vip | self.plain, [{'name': 'V'}, {'name': 'P'}], {'name': {}, 'website': {}})
        self.assertEqual([row['name'] for row in result], ['V', 'P'])
        self.assertIs(result[0]['website'], False)
        self.assertEqual(result[1]['website'], 'http://plain.example.com')

    def test_web_save_on_several_records_judges_each_one(self):
        for records in (self.plain | self.locked, self.locked | self.plain):
            with self.subTest(order=records.mapped('ref')):
                (self.plain | self.locked).write({'function': 'F0'})
                self._call('res.partner', 'web_save', [records.ids, {'function': 'F1'}], {'specification': {}})
                (self.plain | self.locked).invalidate_recordset()
                self.assertEqual((self.plain.function, self.locked.function), ('F1', 'F0'))

    def test_web_save_on_several_records_reads_back_without_hidden_values(self):
        result = self._call('res.partner', 'web_save', [(self.vip | self.plain).ids, {'function': 'F2'}],
                            {'specification': {'function': {}, 'website': {}}})
        self.assertEqual({row['function'] for row in result}, {'F2'})
        self.assertEqual({row['website'] for row in result}, {False, 'http://plain.example.com'})


@tagged('post_install', '-at_install')
class TestExportProfiles(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = new_test_user(cls.env, 'gec_codex_export_plain', groups='base.group_user',
                                       password=cls.password)
        cls.manager = new_test_user(cls.env, 'gec_codex_export_manager',
                                    groups='base.group_user,gec_access_manager.group_access_manager',
                                    password=cls.password)
        cls.profiles = cls.env['gec.access.profile'].create([{'name': 'Codex export'}, {'name': 'Codex export 2'}])

    @mute_logger('odoo.http')
    def test_only_a_manager_exports_the_profiles(self):
        """ Two profiles: the file is named without reading a profile, so only the access check stops it. """
        Attachment = self.env['ir.attachment']
        domain = [('name', '=', 'access_profiles.json')]
        before = Attachment.search_count(domain)
        self.authenticate(self.plain_user.login, self.password)
        with self.assertRaises(JsonRpcException):
            self._call('gec.access.profile', 'action_export_profiles', [self.profiles.ids])
        self.assertEqual(Attachment.search_count(domain), before)
        self.authenticate(self.manager.login, self.password)
        action = self._call('gec.access.profile', 'action_export_profiles', [self.profiles.ids])
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])
        self.assertEqual(Attachment.search_count(domain), before + 1)


@tagged('post_install', '-at_install')
class TestTranslationGuard(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_translation_user',
                                 groups='base.group_user,base.group_partner_manager', password=cls.password)
        Category = cls.env['res.partner.category']
        cls.category = Category.create({'name': 'Translated', 'color': 0})
        cls.other = Category.create({'name': 'Other', 'color': 7})

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _carry(self, mode, **values):
        self.user.access_profile_ids = [Command.set(self.env['gec.access.profile'].create({
            'name': 'Codex translation',
            'field_ids': [self._field_line('res.partner.category', 'name', mode, **values)],
        }).ids)]

    def _name(self, category):
        category.invalidate_recordset()
        return category.with_context(lang='en_US').name

    @mute_logger('odoo.http')
    def test_a_read_only_field_keeps_its_translations(self):
        self._carry('readonly')
        with self.assertRaises(JsonRpcException):
            self._call('res.partner.category', 'update_field_translations',
                       [self.category.ids, 'name', {'en_US': 'Renamed'}])
        with self.assertRaises(JsonRpcException):
            self._call('res.partner.category', 'web_override_translations', [self.category.ids, {'name': 'Overridden'}])
        self.assertEqual(self._name(self.category), 'Translated')

    @mute_logger('odoo.http')
    def test_a_field_locked_under_a_condition_keeps_its_translations_on_matching_records(self):
        self._carry('readonly', condition='color == 7')
        with self.assertRaises(JsonRpcException):
            self._call('res.partner.category', 'update_field_translations',
                       [self.other.ids, 'name', {'en_US': 'Renamed'}])
        with self.assertRaises(JsonRpcException):
            self._call('res.partner.category', 'web_override_translations', [self.other.ids, {'name': 'Overridden'}])
        self.assertEqual(self._name(self.other), 'Other')
        self._call('res.partner.category', 'update_field_translations',
                   [self.category.ids, 'name', {'en_US': 'Renamed'}])
        self.assertEqual(self._name(self.category), 'Renamed')
        self._call('res.partner.category', 'web_override_translations', [self.category.ids, {'name': 'Overridden'}])
        self.assertEqual(self._name(self.category), 'Overridden')

    @mute_logger('odoo.http')
    def test_the_translation_dialog_routes_are_guarded(self):
        self._carry('readonly')
        params = {'res_model': 'res.partner.category', 'field_name': 'name', 'res_id': self.category.id}
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request('/web/translations/save_translation_for_field',
                                      dict(params, changes={'en_US': 'Renamed'}))
        self.assertEqual(self._name(self.category), 'Translated')
        self._carry('hide')
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request('/web/translations/get_translation_for_field', params)

    @mute_logger('odoo.http')
    def test_the_website_translation_route_is_guarded(self):
        if not self.env['ir.module.module'].search_count([('name', '=', 'website'), ('state', '=', 'installed')]):
            self.skipTest("website is not installed")
        params = {'model': 'res.partner.category', 'record_id': self.category.id, 'field_name': 'name',
                  'translations': {'en_US': 'Renamed'}}
        self._carry('readonly')
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request('/website/field/translation/update', params)
        self.assertEqual(self._name(self.category), 'Translated')
        self.user.access_profile_ids = [Command.clear()]
        self.make_jsonrpc_request('/website/field/translation/update', params)
        self.assertEqual(self._name(self.category), 'Renamed')

    def _markup_record(self):
        """ A record the user reads, with a field the dialog reads in its xml or html mode, or None. """
        lines = self.env['ir.model.fields'].search([
            ('translate', 'in', ('html_translate', 'xml_translate')), ('store', '=', True)])
        for line in lines:
            if line.model not in self.env:
                continue
            model = self.env[line.model].with_user(self.user)
            if not model.has_access('read'):
                continue
            record = model.search([], limit=1)
            if record and record.has_field_access(model._fields[line.name], 'read'):
                return record, line.name
        return None

    @mute_logger('odoo.http')
    def test_the_dialog_does_not_read_a_hidden_xml_or_html_field(self):
        found = self._markup_record()
        if not found:
            self.skipTest("no xml or html translated field the user can read")
        record, field_name = found
        params = {'res_model': record._name, 'field_name': field_name, 'res_id': record.id, 'target_lang': 'en_US'}
        self.assertIn('xml_values', self.make_jsonrpc_request('/web/translations/get_translation_for_field', params))
        self.user.access_profile_ids = [Command.set(self.env['gec.access.profile'].create({
            'name': 'Codex markup translation',
            'field_ids': [self._field_line(record._name, field_name, 'hide')],
        }).ids)]
        with self.assertRaises(JsonRpcException):
            self.make_jsonrpc_request('/web/translations/get_translation_for_field', params)


@tagged('post_install', '-at_install')
class TestViewFields(TransactionCase):

    def test_the_fields_a_condition_reads_are_declared_and_nothing_else(self):
        if 'sale.order' not in self.env:
            self.skipTest("sale is not installed")
        user = new_test_user(self.env, 'gec_codex_view_user', groups='base.group_user,sales_team.group_sale_salesman')
        Fields = self.env['ir.model.fields']
        self.env['gec.access.profile'].create({
            'name': 'Codex view',
            'user_ids': [Command.set(user.ids)],
            'field_ids': [Command.create({
                'model_id': self.env['ir.model']._get('sale.order.line').id,
                'field_id': Fields._get('sale.order.line', 'customer_lead').id,
                'mode': 'readonly', 'condition': 'create_uid == 1',
            })],
        })
        views = self.env['sale.order'].with_user(user).get_views([(False, 'form')])
        # the view lacks create_uid: it is loaded, and its description sent
        self.assertIn('create_uid', views['models']['sale.order.line']['fields'])
        arch = etree.fromstring(views['views']['form']['arch'])
        line = arch.xpath("//field[@name='order_line']//list//field[@name='customer_lead']")[0]
        self.assertIn('create_uid == 1', line.get('readonly'))
        self.assertIn('parent.state', line.get('readonly'))
        # parent and context are what an existing expression reads, not fields
        self.assertFalse(arch.xpath("//field[@name='parent']"))
        self.assertFalse(arch.xpath("//field[@name='context']"))


@tagged('post_install', '-at_install')
class TestCompanyProfiles(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'GEC Codex Second'})
        cls.granted = cls.env['res.groups'].create({'name': 'GEC Codex Granted'})
        cls.other = cls.env['res.groups'].create({'name': 'GEC Codex Other'})
        cls.user = new_test_user(cls.env, 'gec_codex_company_user', groups='base.group_user')
        cls.Profile = cls.env['gec.access.profile']

    def _scoped(self, **values):
        return self.Profile.create({
            'name': 'Codex scoped', 'company_id': self.company.id,
            'granted_group_ids': [Command.set(self.granted.ids)], **values})

    def _carries(self, profile, user):
        self.env.invalidate_all()
        in_group = user in profile.group_id.user_ids
        self.assertEqual(self.granted in user.all_group_ids, in_group)
        return in_group

    def test_a_user_outside_the_company_does_not_carry_the_profile(self):
        profile = self._scoped(user_ids=[Command.set(self.user.ids)])
        self.assertFalse(self._carries(profile, self.user))
        self.assertNotIn(self.user, profile._gec_members())
        self.user.write({'company_ids': [Command.link(self.company.id)], 'group_ids': [Command.link(self.other.id)]})
        self.assertTrue(self._carries(profile, self.user))
        self.assertIn(self.user, profile._gec_members())
        self.user.write({'company_ids': [Command.unlink(self.company.id)]})
        self.assertFalse(self._carries(profile, self.user))

    def test_a_running_assignment_follows_the_companies_of_the_user(self):
        profile = self._scoped()
        self.env['gec.access.profile.assignment'].create({
            'profile_id': profile.id, 'user_id': self.user.id, 'date_from': date(2000, 1, 1)})
        self.assertFalse(self._carries(profile, self.user))
        self.user.write({'company_ids': [Command.link(self.company.id)]})
        self.assertTrue(self._carries(profile, self.user))

    def test_an_archived_assignment_no_longer_carries_the_profile(self):
        profile = self.Profile.create({'name': 'Codex assigned', 'granted_group_ids': [Command.set(self.granted.ids)]})
        line = self.env['gec.access.profile.assignment'].create({
            'profile_id': profile.id, 'user_id': self.user.id, 'date_from': date(2000, 1, 1)})
        self.assertEqual(line.state, 'active')
        self.assertTrue(self._carries(profile, self.user))
        line.active = False
        self.assertFalse(self._carries(profile, self.user))
        self.assertNotIn(self.user, profile._gec_members())

    def test_a_new_user_with_a_profile_is_in_its_group(self):
        profile = self.Profile.create({'name': 'Codex new user', 'granted_group_ids': [Command.set(self.granted.ids)]})
        user = self.env['res.users'].create({
            'name': 'Codex New', 'login': 'gec_codex_new_user',
            'group_ids': [Command.link(self.env.ref('base.group_user').id)],
            'access_profile_ids': [Command.set(profile.ids)],
        })
        self.assertTrue(self._carries(profile, user))


@tagged('post_install', '-at_install')
class TestContextDefaults(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_default_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        cls.be, cls.de = cls.env.ref('base.be'), cls.env.ref('base.de')
        cls.env['gec.access.profile'].create({
            'name': 'Codex defaults',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [
                cls._field_line('res.partner', 'phone', 'readonly'),
                cls._field_line('res.partner', 'country_id', 'keep', field_domain=repr([('id', 'in', cls.be.ids)])),
            ],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def _partner(self, name):
        return self.env['res.partner'].search([('name', '=', name)])

    @mute_logger('odoo.http')
    def test_a_default_outside_the_value_filter_is_refused_on_a_new_record(self):
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'web_save', [[], {'name': 'Codex Saved'}],
                       {'specification': {}, 'context': {'default_country_id': self.de.id}})
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'create', [[{'name': 'Codex Saved'}]],
                       {'context': {'default_country_id': self.de.id}})
        self.assertFalse(self._partner('Codex Saved'))
        self._call('res.partner', 'web_save', [[], {'name': 'Codex Saved'}],
                   {'specification': {}, 'context': {'default_country_id': self.be.id}})
        self.assertEqual(self._partner('Codex Saved').country_id, self.be)

    @mute_logger('odoo.http')
    def test_name_create_judges_the_default_of_the_group(self):
        """ A kanban quick create sends name_create with the default of the column it is in. """
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'name_create', ['Codex Quick'], {'context': {'default_country_id': self.de.id}})
        self.assertFalse(self._partner('Codex Quick'))
        self._call('res.partner', 'name_create', ['Codex Quick'], {'context': {'default_country_id': self.be.id}})
        self.assertEqual(self._partner('Codex Quick').country_id, self.be)

    def test_the_default_of_a_read_only_field_is_still_stored(self):
        """ On the web client's doors core fills read-only fields from the action's defaults, so none is refused
        (the API doors refuse them: test_round2_fixes). """
        self._call('res.partner', 'web_save', [[], {'name': 'Codex Default'}],
                   {'specification': {}, 'context': {'default_phone': '555'}})
        self.assertEqual(self._partner('Codex Default').phone, '555')


@tagged('post_install', '-at_install')
class TestSeveralConditions(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_conditions_user',
                                 groups='base.group_user,base.group_partner_manager', password=cls.password)
        Partner = cls.env['res.partner']
        cls.a = Partner.create({'name': 'Cond A', 'ref': 'a', 'function': 'F0'})
        cls.b = Partner.create({'name': 'Cond B', 'ref': 'b', 'function': 'F0'})
        cls.c = Partner.create({'name': 'Cond C', 'ref': 'c', 'function': 'F0'})
        Profile = cls.env['gec.access.profile']
        cls.user.access_profile_ids = [Command.set((Profile.create([{
            'name': 'Codex hide if A', 'strictness': 'override',
            'field_ids': [cls._field_line('res.partner', 'function', 'hide', condition="ref == 'a'")],
        }, {
            'name': 'Codex read only if B', 'strictness': 'override',
            'field_ids': [cls._field_line('res.partner', 'function', 'readonly', condition="ref == 'b'")],
        }])).ids)]

    def test_a_record_locked_by_a_weaker_mode_of_another_profile_is_not_writable(self):
        self.authenticate(self.user.login, self.password)
        for partner in (self.a, self.b, self.c):
            self._call('res.partner', 'write', [partner.ids, {'function': 'F1'}])
        (self.a | self.b | self.c).invalidate_recordset()
        self.assertEqual((self.a.function, self.b.function, self.c.function), ('F0', 'F0', 'F1'))

    def test_the_view_is_read_only_under_both_conditions_and_hidden_under_one(self):
        arch = etree.fromstring(self.env['res.partner'].with_user(self.user).get_view(view_type='form')['arch'])
        nodes = arch.xpath("//field[@name='function']")
        self.assertTrue(nodes)
        readonly = [node.get('readonly') or '' for node in nodes]
        self.assertTrue(any("ref == 'a'" in value and "ref == 'b'" in value for value in readonly), readonly)
        invisible = [node.get('invisible') or '' for node in nodes]
        self.assertTrue(any("ref == 'a'" in value for value in invisible), invisible)
        self.assertFalse(any("ref == 'b'" in value for value in invisible), invisible)


@tagged('post_install', '-at_install')
class TestCopyData(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_copy_user',
                                 groups='base.group_user,base.group_partner_manager,base.group_allow_export',
                                 password=cls.password)
        Partner = cls.env['res.partner']
        cls.vip = Partner.create({'name': 'Copy Vip', 'ref': 'vip', 'website': 'vip.example.com'})
        cls.plain = Partner.create({'name': 'Copy Plain', 'ref': 'plain', 'website': 'plain.example.com'})
        cls.export = cls.env['ir.exports'].create({
            'name': 'Codex copy export', 'resource': 'res.partner',
            'export_fields': [Command.create({'name': 'name'})],
        })
        cls.env['gec.access.profile'].create({
            'name': 'Codex copy',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [
                cls._field_line('res.partner', 'website', 'hide', condition="ref == 'vip'"),
                cls._field_line('ir.exports.line', 'name', 'hide'),
            ],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def test_copy_data_blanks_a_conditionally_hidden_field_on_the_matching_record(self):
        self.assertIs(self._call('res.partner', 'copy_data', [self.vip.ids])[0]['website'], False)
        copied = self._call('res.partner', 'copy_data', [self.plain.ids])
        self.assertEqual(copied[0]['website'], 'http://plain.example.com')

    def test_copy_data_blanks_a_hidden_field_in_the_lines_of_a_copy(self):
        lines = self._call('ir.exports', 'copy_data', [self.export.ids])[0]['export_fields']
        self.assertTrue(lines)
        for command in lines:
            self.assertIs(command[2]['name'], False)


@tagged('post_install', '-at_install')
class TestResequence(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_sequence_user',
                                 groups='base.group_user,base.group_partner_manager', password=cls.password)
        Category = cls.env['res.partner.category']
        cls.a = Category.create({'name': 'Seq A', 'color': 7})
        cls.b = Category.create({'name': 'Seq B', 'color': 3})
        cls.env['gec.access.profile'].create({
            'name': 'Codex sequence',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [
                cls._field_line('res.partner.category', 'color', 'readonly', condition='color == 7'),
                cls._field_line('res.partner.category', 'parent_id', 'keep',
                                field_domain=repr([('id', 'in', cls.a.ids)])),
            ],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def test_a_record_locked_under_a_condition_is_left_out_of_the_new_order(self):
        result = self._call('res.partner.category', 'web_resequence', [[self.a.id, self.b.id], {'color': {}}],
                            {'field_name': 'color', 'offset': 10})
        (self.a | self.b).invalidate_recordset()
        self.assertEqual((self.a.color, self.b.color), (7, 10))
        self.assertEqual({row['id']: row['color'] for row in result}, {self.a.id: 7, self.b.id: 10})

    @mute_logger('odoo.http')
    def test_a_value_filtered_field_is_refused(self):
        with self.assertRaises(JsonRpcException):
            self._call('res.partner.category', 'web_resequence', [[self.a.id, self.b.id], {}],
                       {'field_name': 'parent_id'})


@tagged('post_install', '-at_install')
class TestManyToManyCreate(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_tags_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        Category = cls.env['res.partner.category']
        cls.allowed, cls.other = Category.create([{'name': 'Tag allowed'}, {'name': 'Tag other'}])
        cls.partner = cls.env['res.partner'].create({'name': 'Tagged'})
        cls.env['gec.access.profile'].create({
            'name': 'Codex tags',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [cls._field_line('res.partner', 'category_id', 'keep',
                                          field_domain=repr([('id', 'in', cls.allowed.ids)]))],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    @mute_logger('odoo.http')
    def test_a_new_record_is_refused_in_a_filtered_many2many_and_a_link_of_an_allowed_one_works(self):
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'write', [self.partner.ids, {'category_id': [[0, 0, {'name': 'Tag brand new'}]]}])
        self.assertFalse(self.env['res.partner.category'].search([('name', '=', 'Tag brand new')]))
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'write', [self.partner.ids, {'category_id': [[4, self.other.id]]}])
        self._call('res.partner', 'write', [self.partner.ids, {'category_id': [[4, self.allowed.id]]}])
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.category_id, self.allowed)


@tagged('post_install', '-at_install')
class TestNestedOrder(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_order_user', groups='base.group_user,base.group_partner_manager',
                                 password=cls.password)
        Partner = cls.env['res.partner']
        cls.parent = Partner.create({'name': 'Order Parent'})
        cls.first, cls.second = Partner.create([
            {'name': 'Aaa Order', 'ref': 'b', 'parent_id': cls.parent.id},
            {'name': 'Bbb Order', 'ref': 'a', 'parent_id': cls.parent.id},
        ])
        cls.env['gec.access.profile'].create({
            'name': 'Codex order',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [cls._field_line('res.partner', 'ref', 'hide')],
        })
        cls.specification = {'child_ids': {'fields': {'name': {}}, 'order': 'ref asc'}}

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    def test_a_nested_order_on_a_hidden_field_is_left_out_of_the_read(self):
        """ Sorted by the hidden field the lines would be second, first: the read gives the model's own order. """
        order = [row['id'] for row in self.parent.web_read(self.specification)[0]['child_ids']]
        self.assertEqual(order, [self.second.id, self.first.id])
        rows = self._call('res.partner', 'web_read', [self.parent.ids, self.specification])
        self.assertEqual([row['id'] for row in rows[0]['child_ids']], [self.first.id, self.second.id])

    @mute_logger('odoo.http')
    def test_a_top_level_order_on_a_hidden_field_is_still_refused(self):
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'web_search_read', [[('id', '=', self.parent.id)], {'name': {}}],
                       {'order': 'ref asc'})


@tagged('post_install', '-at_install')
class TestSharedFilters(GuardCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_filters_user', groups='base.group_user', password=cls.password)
        Profile = cls.env['gec.access.profile']
        cls.read_only, cls.open = Profile.create([
            {'name': 'Codex read only', 'global_readonly': True},
            {'name': 'Codex open'},
        ])

    def _shared_filter(self, name):
        return self._call('ir.filters', 'create', [{'name': name, 'model_id': 'res.partner', 'user_ids': []}])

    @mute_logger('odoo.http')
    def test_an_additive_open_profile_lets_the_user_share_a_filter(self):
        self.authenticate(self.user.login, self.password)
        self.user.access_profile_ids = [Command.set(self.read_only.ids)]
        with self.assertRaises(JsonRpcException):
            self._shared_filter('Codex shared alone')
        self.user.access_profile_ids = [Command.set((self.read_only | self.open).ids)]
        self._shared_filter('Codex shared')
        shared = self.env['ir.filters'].search([('name', '=', 'Codex shared')])
        self.assertEqual(len(shared), 1)
        self.assertFalse(shared.user_ids)


def _picture():
    """ A small red PNG, base64 encoded. """
    buffer = io.BytesIO()
    Image.new('RGB', (64, 64), (255, 0, 0)).save(buffer, 'PNG')
    return base64.b64encode(buffer.getvalue()).decode()


class ImageCase(GuardCase):
    """ Contacts with a picture, and the routes that serve it, as a user opens them. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_codex_image_user', groups='base.group_user', password=cls.password)
        cls.free = new_test_user(cls.env, 'gec_codex_image_free', groups='base.group_user', password=cls.password)

    @classmethod
    def _partner_with_picture(cls, name, ref):
        partner = cls.env['res.partner'].create({'name': name, 'ref': ref, 'image_1920': _picture()})
        cls.env.flush_all()
        return partner

    def _attachment(self, partner, field_name):
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'res.partner'), ('res_id', 'in', partner.ids), ('res_field', '=', field_name)])

    def _urls(self, partner):
        """ The routes that serve the picture of a contact: by field, by derived field and by attachment. """
        urls = [f'/web/content/res.partner/{partner.id}/image_1920',
                f'/web/image/res.partner/{partner.id}/image_256',
                f'/web/image/res.partner/{partner.id}/avatar_128']
        for field_name in ('image_1920', 'image_128'):
            attachment = self._attachment(partner, field_name)
            self.assertTrue(attachment, field_name)
            urls += [f'/web/content/{attachment.id}', f'/web/image/{attachment.id}']
        return urls

    def _shows_picture(self, url):
        """ Whether the route serves the red picture: an error page or the grey placeholder does not. """
        response = self.url_open(url)
        if response.status_code != 200:
            return False
        try:
            with Image.open(io.BytesIO(response.content)) as image:
                return image.convert('RGB').getpixel((0, 0)) == (255, 0, 0)
        except OSError:
            return False

    def _search_attachments(self, partners, field_name):
        return self._call('ir.attachment', 'search_read', [[
            ('res_model', '=', 'res.partner'), ('res_id', 'in', partners.ids), ('res_field', '=', field_name)]],
            {'fields': ['res_id']})


@tagged('post_install', '-at_install')
class TestHiddenImage(ImageCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls._partner_with_picture('Hidden Picture', 'hidden')
        cls.env['gec.access.profile'].create({
            'name': 'Codex hidden image',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [cls._field_line('res.partner', 'image_1920', 'hide')],
        })

    @mute_logger('odoo.http')
    def test_a_hidden_image_is_served_by_no_route(self):
        self.authenticate(self.free.login, self.password)
        for url in self._urls(self.partner):
            self.assertTrue(self._shows_picture(url), url)
        self.authenticate(self.user.login, self.password)
        for url in self._urls(self.partner):
            self.assertFalse(self._shows_picture(url), url)

    @mute_logger('odoo.http')
    def test_the_attachments_of_a_hidden_image_are_not_searched_nor_read(self):
        self.authenticate(self.user.login, self.password)
        attachments = self._attachment(self.partner, 'image_1920') | self._attachment(self.partner, 'image_128')
        self.assertEqual(len(attachments), 2)
        for field_name in ('image_1920', 'image_128'):
            self.assertEqual(self._search_attachments(self.partner, field_name), [])
        self.assertEqual(self._call('ir.attachment', 'search_read', [[('id', 'in', attachments.ids)]],
                                    {'fields': ['res_id']}), [])
        with self.assertRaises(JsonRpcException):
            self._call('ir.attachment', 'read', [attachments.ids, ['raw']])

    @mute_logger('odoo.http')
    def test_the_images_derived_from_a_hidden_one_are_not_exported_nor_described(self):
        self.authenticate(self.user.login, self.password)
        with self.assertRaises(JsonRpcException):
            self._call('res.partner', 'export_data', [self.partner.ids, ['image_128']])
        described = self._call('res.partner', 'fields_get', [],
                               {'allfields': ['name', 'image_1920', 'image_128', 'avatar_128']})
        self.assertEqual(list(described), ['name'])

    @mute_logger('odoo.http')
    def test_an_avatar_token_does_not_serve_a_hidden_image(self):
        url = f'/web/image/res.partner/{self.partner.id}/avatar_128?access_token=' \
              f'{self.partner._get_avatar_128_access_token()}'
        self.authenticate(self.free.login, self.password)
        self.assertTrue(self._shows_picture(url))
        self.authenticate(self.user.login, self.password)
        self.assertFalse(self._shows_picture(url))

    def test_the_read_of_the_contact_blanks_the_image_and_the_images_derived_from_it(self):
        self.authenticate(self.user.login, self.password)
        names = ['name', 'image_1920', 'image_1024', 'image_128', 'avatar_128']
        row = self._call('res.partner', 'read', [self.partner.ids, names])[0]
        self.assertEqual(row['name'], 'Hidden Picture')
        for name in names[1:]:
            self.assertIs(row[name], False, name)


@tagged('post_install', '-at_install')
class TestConditionalImage(ImageCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vip = cls._partner_with_picture('Vip Picture', 'vip')
        cls.plain = cls._partner_with_picture('Plain Picture', 'plain')
        cls.env['gec.access.profile'].create({
            'name': 'Codex conditional image',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [cls._field_line('res.partner', 'image_1920', 'hide', condition="ref == 'vip'")],
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.user.login, self.password)

    @mute_logger('odoo.http')
    def test_the_picture_of_the_matching_contact_is_served_by_no_route(self):
        for url in self._urls(self.vip):
            self.assertFalse(self._shows_picture(url), url)
        for url in self._urls(self.plain):
            self.assertTrue(self._shows_picture(url), url)

    @mute_logger('odoo.http')
    def test_the_attachments_of_the_matching_contact_are_not_searched_nor_read(self):
        both = self.vip | self.plain
        for field_name in ('image_1920', 'image_128'):
            self.assertEqual([row['res_id'] for row in self._search_attachments(both, field_name)], [self.plain.id])
        attachments = self._attachment(both, 'image_1920')
        rows = self._call('ir.attachment', 'search_read', [[('id', 'in', attachments.ids)]], {'fields': ['res_id']})
        self.assertEqual([row['res_id'] for row in rows], [self.plain.id])
        with self.assertRaises(JsonRpcException):
            self._call('ir.attachment', 'read', [self._attachment(self.vip, 'image_1920').ids, ['raw']])

    def test_the_read_of_the_contact_blanks_the_images_of_the_matching_record_only(self):
        rows = self._call('res.partner', 'read', [(self.vip | self.plain).ids, ['image_1920', 'image_128']])
        by_id = {row['id']: row for row in rows}
        self.assertEqual((by_id[self.vip.id]['image_1920'], by_id[self.vip.id]['image_128']), (False, False))
        self.assertTrue(by_id[self.plain.id]['image_1920'])
        self.assertTrue(by_id[self.plain.id]['image_128'])


@tagged('post_install', '-at_install')
class TestTransferFields(TransactionCase):
    """ #11: the company, the archived state and the sequence travel with an export and make a version. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'GEC Codex Transfer'})
        cls.profile = cls.env['gec.access.profile'].create({
            'name': 'Codex transfer', 'company_id': cls.company.id, 'sequence': 7})

    def _reimport(self, content):
        self.profile.name = 'Codex transfer (source)'
        return self.env['gec.access.profile']._gec_import(content)

    def test_the_company_and_the_sequence_come_back(self):
        imported = self._reimport(self.profile._gec_export())
        self.assertEqual((imported.company_id, imported.sequence, imported.active), (self.company, 7, True))

    def test_an_archived_profile_comes_back_archived(self):
        self.profile.active = False
        imported = self._reimport(self.profile._gec_export())
        self.assertFalse(imported.active)

    def test_a_missing_company_brings_the_profile_in_archived(self):
        content = self.profile._gec_export().replace('GEC Codex Transfer', 'GEC Codex Elsewhere')
        imported = self._reimport(content)
        self.assertFalse(imported.company_id)
        self.assertFalse(imported.active)

    def test_a_change_of_company_makes_a_version(self):
        data = self.profile._gec_version_data()
        self.profile.company_id = False
        self.assertNotEqual(self.profile._gec_version_data(), data)
        self.assertIn('Company', self.env['gec.access.profile']._gec_diff_summary(data, self.profile._gec_version_data()))


@tagged('post_install', '-at_install')
class TestConditionOnUnsearchableField(ImageCase):
    """ R4-1: a condition on a field SQL cannot search hides the pictures of every contact, breaks no search. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls._partner_with_picture('Any Picture', 'any')
        cls.document = cls.env['ir.attachment'].create({
            'name': 'document', 'res_model': 'res.partner', 'res_id': cls.partner.id, 'raw': b'document'})
        cls.env['gec.access.profile'].create({
            'name': 'Codex unsearchable condition',
            'user_ids': [Command.set(cls.user.ids)],
            'field_ids': [cls._field_line('res.partner', 'image_1920', 'hide', condition='not is_public')],
        })

    def test_the_attachment_search_does_not_fail_and_hides_the_pictures(self):
        self.authenticate(self.user.login, self.password)
        for field_name in ('image_1920', 'image_128'):
            self.assertEqual(self._search_attachments(self.partner, field_name), [])
        rows = self._call('ir.attachment', 'search_read', [[
            ('res_model', '=', 'res.partner'), ('res_id', '=', self.partner.id)]], {'fields': ['name']})
        self.assertEqual([row['id'] for row in rows], self.document.ids)

    def test_a_search_about_another_model_does_not_look_at_the_rule(self):
        self.authenticate(self.user.login, self.password)
        rows = self._call('ir.attachment', 'search_read', [[('res_model', '=', 'res.users')]], {'fields': ['name']})
        self.assertIsInstance(rows, list)


@tagged('post_install', '-at_install')
class TestLockedImageWrite(ImageCase):
    """ R4-6: the file of a locked image is not written through its attachment; the other files are. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer = new_test_user(cls.env, 'gec_codex_image_writer',
                                   groups='base.group_user,base.group_partner_manager', password=cls.password)
        cls.vip = cls._partner_with_picture('Vip Writer', 'vip')
        cls.plain = cls._partner_with_picture('Plain Writer', 'plain')
        cls.document = cls.env['ir.attachment'].create({
            'name': 'document', 'res_model': 'res.partner', 'res_id': cls.plain.id, 'raw': b'document'})

    def _carry(self, **values):
        self.writer.access_profile_ids = [Command.set(self.env['gec.access.profile'].create({
            'name': 'Codex locked image',
            'field_ids': [self._field_line('res.partner', 'image_1920', 'readonly', **values)],
        }).ids)]
        self.authenticate(self.writer.login, self.password)

    def _write_raw(self, attachment):
        self._call('ir.attachment', 'write', [attachment.ids, {'raw': base64.b64encode(b'tampered').decode()}])
        attachment.invalidate_recordset()

    @mute_logger('odoo.http')
    def test_a_read_only_image_is_not_written_through_its_attachment(self):
        self._carry()
        for field_name in ('image_1920', 'image_128'):
            attachment = self._attachment(self.plain, field_name)
            before = attachment.checksum
            with self.assertRaises(JsonRpcException):
                self._write_raw(attachment)
            attachment.invalidate_recordset()
            self.assertEqual(attachment.checksum, before, field_name)
        self._write_raw(self.document)
        self.assertEqual(self.document.checksum, hashlib.sha1(b'tampered').hexdigest())

    @mute_logger('odoo.http')
    def test_an_image_read_only_under_a_condition_is_not_written_on_the_matching_contact(self):
        self._carry(condition="ref == 'vip'")
        locked = self._attachment(self.vip, 'image_1920')
        before = locked.checksum
        with self.assertRaises(JsonRpcException):
            self._write_raw(locked)
        locked.invalidate_recordset()
        self.assertEqual(locked.checksum, before)
        free = self._attachment(self.plain, 'image_1920')
        free_before = free.checksum
        self._write_raw(free)
        self.assertNotEqual(free.checksum, free_before)


@tagged('post_install', '-at_install')
class TestVersionsAfterNewKeys(TransactionCase):
    """ R4-7: a version stored before the export carried 'active', 'sequence' and 'company' is no change. """

    def setUp(self):
        super().setUp()
        self.env.cr.precommit.run()

    def _commit(self):
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _versions(self, profile):
        return self.env['gec.access.profile.version'].search([('profile_id', '=', profile.id)], order='number')

    def test_a_write_changing_nothing_makes_no_version_after_the_upgrade(self):
        profile = self.env['gec.access.profile'].create({'name': 'Codex old version'})
        self._commit()
        version = self._versions(profile)
        data = json.loads(version.data)
        for key in ('active', 'sequence', 'company'):
            data.pop(key, None)
        version.write({'data': json.dumps(data, sort_keys=True)})
        profile.write({'name': 'Codex old version'})
        self._commit()
        self.assertEqual(len(self._versions(profile)), 1)
        profile.write({'block_export': True})
        self._commit()
        latest = self._versions(profile)[-1]
        self.assertEqual(latest.number, 2)
        self.assertIn('Block Export', latest.summary)
        self.assertNotIn('Active', latest.summary)
        self.assertNotIn('Sequence', latest.summary)
