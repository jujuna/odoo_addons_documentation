import json
from datetime import date, datetime
from types import SimpleNamespace
from unittest import SkipTest
from unittest.mock import patch

from freezegun import freeze_time
from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.http import routing_map
from odoo.modules.registry import Registry
from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tests.common import get_db_name

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.gec_access_manager.controllers import mail as mail_controller
from odoo.addons.mail.controllers import thread as thread_controller

from .test_codex_fixes import _picture


def _field_line(env, model_name, field_name, mode, **values):
    return Command.create({
        'model_id': env['ir.model']._get(model_name).id,
        'field_id': env['ir.model.fields']._get(model_name, field_name).id,
        'mode': mode, **values,
    })


@tagged('post_install', '-at_install')
class TestHiddenImageForSettingsUsers(TransactionCase):
    """ A Settings user under a profile applying to them is refused the hidden pictures by attachment id. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.vip = Partner.create({'name': 'Open Vip', 'ref': 'vip', 'image_1920': _picture()})
        cls.plain = Partner.create({'name': 'Open Plain', 'ref': 'plain', 'image_1920': _picture()})
        cls.env.flush_all()
        cls.always = new_test_user(cls.env, 'gec_open_settings_always', groups='base.group_user,base.group_system')
        cls.conditional = new_test_user(
            cls.env, 'gec_open_settings_conditional', groups='base.group_user,base.group_system')
        for user, condition in ((cls.always, False), (cls.conditional, "ref == 'vip'")):
            cls.env['gec.access.profile'].create({
                'name': f'Open settings {user.login}', 'apply_to_admin': True, 'user_ids': [Command.set(user.ids)],
                'field_ids': [_field_line(cls.env, 'res.partner', 'image_1920', 'hide', condition=condition)],
            })
        cls.domain = [
            ('res_model', '=', 'res.partner'), ('res_id', 'in', (cls.vip | cls.plain).ids),
            ('res_field', 'in', ['image_1920', 'image_128'])]

    def test_an_always_hidden_picture_is_not_given_to_a_settings_user(self):
        attachments = self.env['ir.attachment'].search(self.domain)
        self.assertEqual(len(attachments), 4)
        self.assertFalse(self.env['ir.attachment'].with_user(self.always).search(self.domain))
        for attachment in attachments:
            self.assertFalse(attachment.with_user(self.always).has_access('read'))

    def test_a_picture_hidden_under_a_condition_is_not_given_to_a_settings_user(self):
        attachments = self.env['ir.attachment'].search(self.domain)
        found = self.env['ir.attachment'].with_user(self.conditional).search(self.domain)
        self.assertEqual(sorted(found.mapped('res_id')), [self.plain.id, self.plain.id])
        for attachment in attachments:
            self.assertEqual(
                attachment.with_user(self.conditional).has_access('read'), attachment.res_id == self.plain.id)


@tagged('post_install', '-at_install')
class TestConditionalRequired(TransactionCase):
    """ A line making a field read only under a condition does not make it required under the same condition. """

    def test_a_conditional_read_only_line_sets_no_required_condition(self):
        user = new_test_user(self.env, 'gec_open_required', groups='base.group_user,base.group_partner_manager')
        self.env['gec.access.profile'].create({
            'name': 'Open required', 'user_ids': [Command.set(user.ids)],
            'field_ids': [
                _field_line(self.env, 'res.partner', 'email', 'readonly', condition="ref == 'locked'"),
                _field_line(self.env, 'res.partner', 'phone', 'required', condition="ref == 'must'"),
            ],
        })
        tree = etree.fromstring('<form><field name="email"/><field name="phone"/></form>')
        profile = self.env['gec.access.profile'].with_user(user)
        profile._apply_view_rules(profile._current_rules(), tree, 'res.partner', tree.tag)
        email, phone = tree.xpath('//field[@name="email"]')[0], tree.xpath('//field[@name="phone"]')[0]
        self.assertEqual(email.get('readonly'), "ref == 'locked'")
        self.assertIsNone(email.get('required'))
        self.assertEqual(phone.get('required'), "ref == 'must'")
        self.assertIsNone(phone.get('readonly'))

    def test_an_always_read_only_field_gets_no_required_condition_from_another_profile(self):
        user = new_test_user(self.env, 'gec_open_required_locked', groups='base.group_user,base.group_partner_manager')
        for name, mode, values in (('locked', 'readonly', {}), ('must', 'required', {'condition': "ref == 'must'"})):
            self.env['gec.access.profile'].create({
                'name': f'Open required {name}', 'strictness': 'override', 'user_ids': [Command.set(user.ids)],
                'field_ids': [_field_line(self.env, 'res.partner', 'phone', mode, **values)],
            })
        tree = etree.fromstring('<form><field name="phone"/></form>')
        profile = self.env['gec.access.profile'].with_user(user)
        profile._apply_view_rules(profile._current_rules(), tree, 'res.partner', tree.tag)
        phone = tree.xpath('//field[@name="phone"]')[0]
        self.assertEqual(phone.get('readonly'), '1')
        self.assertIsNone(phone.get('required'))


@tagged('post_install', '-at_install')
class TestLoadModelsMenuRules(TransactionCase):
    """ Load Models does not add a row for data a menu rule covers: the row would win over the menu rule. """

    def test_the_models_of_a_menu_with_a_rule_are_not_loaded(self):
        Action, Menu = self.env['ir.actions.act_window'], self.env['ir.ui.menu']
        tags = Action.create({'name': 'GEC Open Tags', 'res_model': 'res.partner.category'})
        industries = Action.create({'name': 'GEC Open Industries', 'res_model': 'res.partner.industry'})
        covered = Menu.create({'name': 'GEC Open Tags', 'action': f'ir.actions.act_window,{tags.id}'})
        free = Menu.create({'name': 'GEC Open Industries', 'action': f'ir.actions.act_window,{industries.id}'})
        profile = self.env['gec.access.profile'].create({'name': 'Open load models'})
        self.env['gec.access.profile.menu'].create({
            'profile_id': profile.id, 'menu_id': covered.id, 'perm_write': False, 'include_shared': True})
        self.env['gec.access.load.models'].create({
            'profile_id': profile.id, 'menu_ids': [Command.set((covered | free).ids)]}).action_load()
        self.assertEqual(profile.model_ids.model_id.mapped('model'), ['res.partner.industry'])


@tagged('post_install', '-at_install')
class TestCopyRestrictionsNotice(TransactionCase):

    def test_the_lines_kept_because_the_target_has_them_are_named(self):
        Profile = self.env['gec.access.profile']
        source = Profile.create({
            'name': 'Open copy source', 'field_ids': [_field_line(self.env, 'res.partner', 'email', 'hide')]})
        target = Profile.create({
            'name': 'Open copy target', 'field_ids': [_field_line(self.env, 'res.partner', 'email', 'readonly')]})
        result = self.env['gec.access.copy.restrictions'].create(
            {'profile_id': target.id, 'source_id': source.id}).action_copy()
        self.assertEqual((result['type'], result['tag']), ('ir.actions.client', 'display_notification'))
        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn('Open copy target', result['params']['message'])
        self.assertIn('Email: Read Only', result['params']['message'])
        self.assertNotIn('Email: Hidden', result['params']['message'])
        self.assertEqual(target.field_ids.mode, 'readonly')
        empty = Profile.create({'name': 'Open copy empty'})
        result = self.env['gec.access.copy.restrictions'].create(
            {'profile_id': empty.id, 'source_id': source.id}).action_copy()
        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})


@tagged('post_install', '-at_install')
class TestImportWithoutUsers(TransactionCase):

    def test_a_file_with_an_empty_user_list_clears_the_members(self):
        Profile = self.env['gec.access.profile']
        user = new_test_user(self.env, 'gec_open_member', groups='base.group_user')
        profile = Profile.create({'name': 'Open members', 'user_ids': [Command.set(user.ids)]})
        data = json.loads(profile._gec_export(with_users=True))
        self.assertEqual(data['profiles'][0]['users'], ['gec_open_member'])
        data['profiles'][0]['users'] = []
        imported = Profile._gec_import(json.dumps(data), replace=True, with_users=True)
        self.assertEqual(imported, profile)
        self.assertFalse(profile.user_ids)


@tagged('post_install', '-at_install')
class TestImportCompanyXmlid(TransactionCase):

    def test_an_xmlid_scoped_to_a_company_is_taken_only_for_the_same_company(self):
        if 'account.journal' not in self.env:
            self.skipTest("account is not installed")
        company = self.env['res.company'].create({'name': 'GEC Open Company'})
        journal = self.env['account.journal'].create({
            'name': 'GEC Open Journal', 'code': 'GOJ', 'type': 'general', 'company_id': company.id})
        name = f'{company.id}_gec_open'
        self.env['ir.model.data'].create({
            'module': 'gec_open_test', 'name': name, 'model': 'account.journal', 'res_id': journal.id})
        Profile = self.env['gec.access.profile']
        xmlid = f'gec_open_test.{name}'
        self.assertEqual(Profile._gec_ref(journal)['company'], 'GEC Open Company')
        self.assertFalse(Profile._gec_find(
            {'xmlid': xmlid, 'name': 'Nowhere', 'company': 'Another Company'}, 'account.journal'))
        self.assertEqual(Profile._gec_find(
            {'xmlid': xmlid, 'name': 'Nowhere', 'company': 'GEC Open Company'}, 'account.journal'), journal)
        self.assertEqual(Profile._gec_find({'xmlid': xmlid, 'name': 'Nowhere'}, 'account.journal'), journal)


@tagged('post_install', '-at_install')
class TestOwnRecordsLevel(TransactionCase):

    def test_a_level_change_keeps_the_saved_own_records_scope(self):
        action = self.env['ir.actions.act_window'].create({'name': 'GEC Open Partners', 'res_model': 'res.partner'})
        app = self.env['ir.ui.menu'].create({'name': 'GEC Open App'})
        self.env['ir.ui.menu'].create({
            'name': 'Partners', 'parent_id': app.id, 'action': f'ir.actions.act_window,{action.id}'})
        profile = self.env['gec.access.profile'].create({'name': 'Open own records'})
        Wizard = type(self.env['gec.access.app.wizard'])

        def wizard_form():
            return Form(self.env['gec.access.app.wizard'].with_context(
                active_model='gec.access.profile', active_id=profile.id))

        # a menu made here has no module: the app owns its data only by these two answers
        with patch.object(Wizard, '_app_modules', return_value={'gec_access_manager'}), \
                patch.object(Wizard, '_creating_modules', return_value={'res.partner': 'gec_access_manager'}):
            form = wizard_form()
            form.app_id = app
            form.own_records = True
            form.save().action_apply()
            row = profile.model_ids.filtered(lambda row: row.model_id.model == 'res.partner')
            self.assertEqual(row.domain, "[('user_id', '=', uid)]")
            form = wizard_form()
            form.app_id = app
            form.level = 'readonly'
            wizard = form.save()
            self.assertEqual(wizard.model_line_ids.filtered(lambda line: line.model_id.model == 'res.partner').scope,
                             'own')
            wizard.action_apply()
        self.assertEqual((row.perm_write, row.domain), (False, "[('user_id', '=', uid)]"))


@tagged('post_install', '-at_install')
class TestInvoiceAnalysisJournals(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        if 'account.journal' not in Registry(get_db_name()):
            raise SkipTest("account is not installed")
        super().setUpClass()
        cls.allowed = cls.company_data['default_journal_sale']
        cls.other = cls.env['account.journal'].create({'name': 'GEC Open Sales', 'code': 'GOS', 'type': 'sale'})
        cls.allowed_invoice = cls._create_invoice('out_invoice', post=True, journal_id=cls.allowed.id)
        cls.other_invoice = cls._create_invoice('out_invoice', post=True, journal_id=cls.other.id)

    def test_allowed_journals_filter_the_invoice_analysis(self):
        user = new_test_user(self.env, 'gec_open_analyst', groups='base.group_user,account.group_account_readonly')
        domain = [('move_id', 'in', (self.allowed_invoice | self.other_invoice).ids)]
        self.assertEqual(self.env['account.invoice.report'].with_user(user).search(domain).move_id,
                         self.allowed_invoice | self.other_invoice)
        self.env['gec.access.profile'].sudo().create({
            'name': 'Open journals', 'user_ids': [Command.set(user.ids)],
            'allowed_ids': [Command.create({'kind': 'journal', 'res_id': self.allowed.id})],
        })
        self.assertEqual(self.env['account.invoice.report'].with_user(user).search(domain).move_id,
                         self.allowed_invoice)


@tagged('post_install', '-at_install')
class TestAssignmentTriggers(TransactionCase):

    def test_an_assignment_wakes_the_refresh_cron_after_local_midnight(self):
        user = new_test_user(self.env, 'gec_open_tbilisi', groups='base.group_user')
        user.tz = 'Asia/Tbilisi'
        profile = self.env['gec.access.profile'].create({'name': 'Open trigger'})
        cron = self.env.ref('gec_access_manager.ir_cron_refresh_assignments')

        def calls():
            return sorted(self.env['ir.cron.trigger'].search([
                ('cron_id', '=', cron.id), ('call_at', '>', datetime(2026, 11, 6))]).mapped('call_at'))

        with freeze_time('2026-11-05 10:00:00'):
            line = self.env['gec.access.profile.assignment'].create({
                'profile_id': profile.id, 'user_id': user.id,
                'date_from': date(2026, 11, 10), 'date_to': date(2026, 11, 12)})
            self.assertEqual(calls(), [datetime(2026, 11, 9, 20, 1), datetime(2026, 11, 12, 20, 1)])
            line.date_from = date(2026, 11, 11)
            self.assertIn(datetime(2026, 11, 10, 20, 1), calls())


@tagged('post_install', '-at_install')
class TestSendMessageHook(TransactionCase):
    """ The chatter check judges the subtype and the recipients core decided on, not the raw request. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_open_sender', groups='base.group_user,base.group_partner_manager')
        cls.reader = new_test_user(cls.env, 'gec_open_reader', groups='base.group_user')
        cls.receiver = new_test_user(cls.env, 'gec_open_receiver', groups='base.group_user')
        cls.partner = cls.env['res.partner'].create({'name': 'Open Thread'})
        cls.role = cls.env['res.role'].create({'name': 'GEC Open Role', 'user_ids': [Command.link(cls.receiver.id)]})
        cls.env['gec.access.profile'].create({
            'name': 'Open no sending', 'hide_send_message_all': True,
            'user_ids': [Command.set((cls.user | cls.reader).ids)]})

    def _prepare(self, user=None, thread=None, **post_data):
        user = user or self.user
        request = SimpleNamespace(env=self.env(user=user))
        with patch.object(mail_controller, 'request', request), patch.object(thread_controller, 'request', request), \
                patch.object(routing_map, 'request', request):
            return mail_controller.ThreadAccess()._prepare_message_data(
                post_data, thread=(thread or self.partner).with_user(user))

    def test_a_post_with_no_subtype_is_a_note_and_passes(self):
        self.assertNotIn('subtype_xmlid', self._prepare(body='Hello'))
        self.assertEqual(self._prepare(body='Hello', subtype_xmlid='mail.mt_note')['subtype_xmlid'], 'mail.mt_note')
        with self.assertRaises(AccessError):
            self._prepare(body='Hello', subtype_xmlid='mail.mt_comment')
        with self.assertRaises(AccessError):
            self._prepare(body='Hello', partner_ids=[self.partner.id])
        with self.assertRaises(AccessError):
            self._prepare(body='Hello', role_ids=[self.role.id])

    def test_a_note_core_turns_into_a_comment_for_a_reader_is_refused(self):
        if 'product.template' not in self.env:
            self.skipTest("product is not installed")
        product = self.env['product.template'].create({'name': 'Open Thread Product'})
        # website_sale lets readers post on products; the case needs a thread that asks for write
        with patch.object(type(product), '_mail_post_access', 'write'), self.assertRaises(AccessError):
            self._prepare(user=self.reader, thread=product, body='Hello', subtype_xmlid='mail.mt_note')
