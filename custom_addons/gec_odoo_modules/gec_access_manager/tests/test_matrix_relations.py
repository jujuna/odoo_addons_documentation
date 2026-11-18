# Restricted data reached through relations. Record filters: the outcome equals what the same user gets with no
# profile and a global core access row of the same domain. Hidden fields: the value never reaches the client over
# /web/dataset/call_kw, and a user without the profile does get it.
import hashlib
import io
import unittest
from unittest.mock import patch

from lxml import etree
from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import BinaryBytes, mute_logger

from . import test_codex_fixes

SECRET_EMAIL = 'mx-secret@example.com'
SECRET_PHONE = '+995 555 000 111'
PARTNER_FILTER = "[('ref', '!=', 'mx-hidden')]"
USER_GROUPS = (
    'base.group_user', 'base.group_partner_manager', 'sales_team.group_sale_salesman_all_leads',
    'account.group_account_invoice', 'stock.group_stock_user', 'hr.group_hr_user', 'hr_payroll.group_hr_payroll_user',
)


def png():
    stream = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 30, 30)).save(stream, format='PNG')
    return BinaryBytes(stream.getvalue())


@tagged('post_install', '-at_install', 'gec_matrix')
class RelationCase(test_codex_fixes.GuardCase):
    """ ``user`` carries the profile of the test, ``control`` has the same groups and no profile. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = ','.join(xmlid for xmlid in USER_GROUPS if cls.env.ref(xmlid, raise_if_not_found=False))
        cls.user = new_test_user(cls.env, 'mx_rel_user', groups=groups, password=cls.password,
                                 email='mx.rel.user@example.com')
        cls.control = new_test_user(cls.env, 'mx_rel_control', groups=groups, password=cls.password,
                                    email='mx.rel.control@example.com')
        cls.other = new_test_user(cls.env, 'mx_rel_other', groups='base.group_user', password=cls.password,
                                  email='mx.rel.other@example.com')

    @classmethod
    def _need(cls, *model_names):
        missing = [name for name in model_names if name not in cls.env]
        if missing:
            raise unittest.SkipTest(f"{', '.join(missing)} not installed")

    def setUp(self):
        super().setUp()
        self._rules = []
        self.authenticate(self.user.login, self.password)

    def _profile(self, restrictions=None, fields=(), **values):
        """ A profile of ``user``: a record filter per model of ``restrictions`` ({model: filter text}) and the
        field lines ``fields``. """
        lines = [Command.create({'model_id': self.env['ir.model']._get(model).id, 'domain': domain})
                 for model, domain in (restrictions or {}).items()]
        return self.env['gec.access.profile'].create({
            'name': 'Matrix relations', 'user_ids': [Command.set(self.user.ids)], 'model_ids': lines,
            'field_ids': list(fields), **values})

    def _hide(self, *pairs):
        return [self._field_line(model, name, 'hide') for model, name in pairs]

    def _restrict(self, mode, restrictions):
        """ Replace the restriction in force: a profile of ``user`` or a global core access row, same filters. """
        for rule in self._rules:
            rule.unlink()
        self._rules = []
        if mode == 'profile':
            self._rules = [self._profile(restrictions)]
        elif mode == 'core':
            self._rules = [self.env['ir.access'].create({
                'name': f'Matrix {model}', 'model_id': self.env['ir.model']._get(model).id,
                'group_id': False, 'operation': 'crud', 'domain': domain,
            }) for model, domain in restrictions.items()]
        self.env.invalidate_all()

    def _result_of(self, call):
        """ What ``call`` returns, or 'refused' for an access error (from the ORM or from the client's call). """
        self.env.invalidate_all()
        try:
            return call()
        except AccessError:
            return 'refused'
        except JsonRpcException as error:
            if 'AccessError' not in str(error):
                raise
            return 'refused'

    @mute_logger('odoo.http')
    def _parity(self, call, restrictions, changes=True):
        """ ``call`` under a profile and under the equivalent core row must give the same outcome; with
        ``changes`` it must also differ from the unrestricted one, so the restriction proves to be in force. """
        self._restrict(None, {})
        baseline = self._result_of(call)
        self._restrict('profile', restrictions)
        by_profile = self._result_of(call)
        self._restrict('core', restrictions)
        by_core = self._result_of(call)
        self.assertEqual(by_profile, by_core)
        if changes:
            self.assertNotEqual(by_core, baseline)
        return baseline, by_core

    def _as_user(self, model):
        return self.env[model].with_user(self.user)

    def _value(self, user, model, record, field, method='read'):
        """ The value the client of ``user`` gets for ``record.field``. """
        self.authenticate(user.login, self.password)
        if method == 'read':
            rows = self._call(model, 'read', [record.ids, [field]])
        else:
            rows = self._call(model, 'web_read', [record.ids], {'specification': {field: {}}})
        return rows[0][field]

    def _assert_not_leaked(self, hidden, model, record, field, secret=None, **profile_values):
        """ A user without the profile reads ``secret`` (any value when None) from ``record.field``; the user whose
        profile hides the (model, field) pairs of ``hidden`` gets nothing, by read and by web_read. """
        self._profile(fields=self._hide(*hidden), **profile_values)
        for method in ('read', 'web_read'):
            with self.subTest(model=model, field=field, method=method):
                value = self._value(self.control, model, record, field, method)
                if secret is None:
                    self.assertTrue(value)
                else:
                    self.assertEqual(value, secret)
                self.assertFalse(self._value(self.user, model, record, field, method))


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixRecordRelations(RelationCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('res.partner', 'sale.order', 'sale.order.line', 'mail.message')
        Partner = cls.env['res.partner']
        cls.shown = Partner.create({'name': 'MX Shown Partner', 'ref': 'mx-shown'})
        cls.hidden = Partner.create({'name': 'MX Hidden Partner', 'ref': 'mx-hidden'})
        cls.parent = Partner.create({'name': 'MX Parent Company', 'is_company': True})
        cls.kid_shown = Partner.create({'name': 'MX Kid Shown', 'parent_id': cls.parent.id})
        cls.kid_hidden = Partner.create({'name': 'MX Kid Hidden', 'parent_id': cls.parent.id, 'ref': 'mx-hidden'})
        Tag = cls.env['res.partner.category']
        cls.tag_shown, cls.tag_hidden = Tag.create([{'name': 'MX Shown Tag'}, {'name': 'MX Hidden Tag'}])
        cls.tagged = Partner.create({'name': 'MX Tagged', 'category_id': [Command.set((cls.tag_shown | cls.tag_hidden).ids)]})
        cls.product = cls.env['product.product'].create({'name': 'MX Product', 'list_price': 10.0, 'standard_price': 4.0})
        Order = cls.env['sale.order']
        cls.order_shown = Order.create({'partner_id': cls.shown.id, 'order_line': [
            Command.create({'product_id': cls.product.id, 'product_uom_qty': 1}),
            Command.create({'product_id': cls.product.id, 'product_uom_qty': 2, 'name': 'MX hidden line'}),
        ]})
        cls.order_hidden = Order.create({'partner_id': cls.hidden.id, 'order_line': [
            Command.create({'product_id': cls.product.id, 'product_uom_qty': 1})]})
        cls.orders = cls.order_shown | cls.order_hidden
        cls.users = cls.user | cls.control | cls.other
        cls.other.partner_id.ref = 'mx-hidden'

    def test_many2one_of_a_restricted_partner_is_read_like_core(self):
        spec = {'name': {}, 'partner_id': {'fields': {'display_name': {}}}}
        self._parity(lambda: {order.id: self._as_user('sale.order').browse(order.id).web_read(spec)
                              for order in self.orders}, {'res.partner': PARTNER_FILTER}, changes=False)
        self._parity(lambda: {order.id: self._as_user('sale.order').browse(order.id).read(['partner_id'])
                              for order in self.orders}, {'res.partner': PARTNER_FILTER}, changes=False)
        self._parity(lambda: self._call('sale.order', 'web_read', [self.orders.ids], {'specification': spec}),
                     {'res.partner': PARTNER_FILTER}, changes=False)

    def test_name_search_of_an_order_by_a_restricted_partner_name_is_like_core(self):
        restrictions = {'res.partner': PARTNER_FILTER}
        baseline, restricted = self._parity(
            lambda: self._as_user('sale.order').with_context(sale_show_partner_name=True).name_search(
                'MX Hidden Partner', domain=[('id', 'in', self.orders.ids)]), restrictions)
        self.assertEqual([order_id for order_id, _name in baseline], self.order_hidden.ids)
        self.assertFalse(restricted)
        self._parity(lambda: self._as_user('sale.order').search([('partner_id.name', 'ilike', 'MX Hidden')]).ids,
                     restrictions)
        self._parity(lambda: self._as_user('sale.order').search_count([('partner_id', 'any', [('ref', '=', 'mx-hidden')])]),
                     restrictions)
        self._parity(lambda: self._call('sale.order', 'web_name_search', ['MX Hidden Partner', {'name': {}}], {
            'domain': [('id', 'in', self.orders.ids)], 'context': {'sale_show_partner_name': True}}), restrictions)

    def test_group_by_a_restricted_partner_is_like_core(self):
        self._parity(lambda: self._as_user('sale.order').formatted_read_group(
            [('id', 'in', self.orders.ids)], ['partner_id'], ['__count']), {'res.partner': PARTNER_FILTER},
            changes=False)
        self._parity(lambda: self._call('sale.order', 'formatted_read_group', [], {
            'domain': [('id', 'in', self.orders.ids)], 'groupby': ['partner_id'], 'aggregates': ['__count']}),
            {'res.partner': PARTNER_FILTER}, changes=False)
        self._parity(lambda: self._call('sale.order', 'web_read_group', [], {
            'domain': [('id', 'in', self.orders.ids)], 'groupby': ['partner_id'], 'aggregates': ['__count']}),
            {'res.partner': PARTNER_FILTER}, changes=False)

    def test_order_lines_restricted_by_a_filter_are_read_like_core(self):
        restrictions = {'sale.order.line': "[('name', 'not ilike', 'MX hidden line')]"}
        order = self.order_shown
        hidden_line = order.order_line.filtered(lambda line: line.name == 'MX hidden line')
        self.assertTrue(hidden_line)
        self._parity(lambda: self._as_user('sale.order').browse(order.id).read(['order_line'])[0]['order_line'],
                     restrictions, changes=False)
        self._parity(lambda: self._as_user('sale.order').browse(order.id).order_line.ids, restrictions, changes=False)
        self._parity(lambda: self._as_user('sale.order').browse(order.id).web_read(
            {'order_line': {'fields': {'name': {}}}}), restrictions)
        self._parity(lambda: self._call('sale.order', 'web_read', [order.ids], {
            'specification': {'order_line': {'fields': {'name': {}}}}}), restrictions)
        self._parity(lambda: {line.id: self._result_of(lambda: self._as_user('sale.order.line').browse(line.id).read(['name']))
                              for line in order.order_line}, restrictions)
        baseline, restricted = self._parity(
            lambda: self._as_user('sale.order.line').search([('order_id', '=', order.id)]).ids, restrictions)
        self.assertEqual(set(baseline) - set(restricted), set(hidden_line.ids))

    def test_the_stored_total_of_an_order_counts_its_restricted_lines_like_core(self):
        self._parity(lambda: self._as_user('sale.order').browse(self.order_shown.id).read(['amount_total']),
                     {'sale.order.line': "[('name', 'not ilike', 'MX hidden line')]"}, changes=False)

    def test_children_restricted_by_a_filter_are_read_like_core(self):
        restrictions = {'res.partner': PARTNER_FILTER}
        parent = self.parent
        baseline, restricted = self._parity(
            lambda: self._as_user('res.partner').browse(parent.id).read(['child_ids'])[0]['child_ids'], restrictions)
        self.assertEqual(set(baseline), set(parent.child_ids.ids))
        self.assertEqual(restricted, self.kid_shown.ids)
        self._parity(lambda: self._as_user('res.partner').browse(parent.id).web_read(
            {'child_ids': {'fields': {'display_name': {}}}}), restrictions)
        self._parity(lambda: self._call('res.partner', 'web_read', [parent.ids], {
            'specification': {'child_ids': {'fields': {'display_name': {}}}}}), restrictions)
        self._parity(lambda: self._as_user('res.partner').browse(parent.id).child_ids.ids, restrictions)

    def test_tags_restricted_by_a_filter_are_read_like_core(self):
        restrictions = {'res.partner.category': "[('name', '!=', 'MX Hidden Tag')]"}
        partner = self.tagged
        baseline, restricted = self._parity(
            lambda: self._as_user('res.partner').browse(partner.id).read(['category_id'])[0]['category_id'],
            restrictions)
        self.assertEqual(set(baseline), set(partner.category_id.ids))
        self.assertEqual(restricted, self.tag_shown.ids)
        self._parity(lambda: self._as_user('res.partner').browse(partner.id).web_read(
            {'category_id': {'fields': {'display_name': {}}}}), restrictions)
        self._parity(lambda: self._call('res.partner', 'web_read', [partner.ids], {
            'specification': {'category_id': {'fields': {'display_name': {}}}}}), restrictions)
        self._parity(lambda: self._as_user('res.partner').search(
            [('id', '=', partner.id), ('category_id.name', '=', 'MX Hidden Tag')]).ids, restrictions)

    def test_users_follow_the_filter_of_their_partner_like_core(self):
        restrictions = {'res.partner': PARTNER_FILTER}
        baseline, restricted = self._parity(
            lambda: self._as_user('res.users').search([('id', 'in', self.users.ids)]).ids, restrictions)
        self.assertEqual(set(baseline), set(self.users.ids))
        self.assertEqual(set(restricted), set((self.user | self.control).ids))
        self._parity(lambda: self._as_user('res.users').browse(self.other.id).read(['name']), restrictions)
        self._parity(lambda: self._as_user('res.users').browse(self.other.id).write({'name': 'Renamed'}), restrictions,
                     changes=False)
        self._parity(lambda: self._call('res.users', 'web_search_read', [], {
            'domain': [('id', 'in', self.users.ids)], 'specification': {'name': {}}}), restrictions)

    def _chatter_of_the_hidden_partner(self):
        hidden = self.hidden
        hidden.message_post(body='MX secret note', message_type='comment', subtype_xmlid='mail.mt_note')
        hidden.message_subscribe(partner_ids=self.shown.ids)
        hidden.activity_schedule('mail.mail_activity_data_todo', summary='MX secret', user_id=self.other.id)
        hidden.image_1920 = png()
        self.attachment = self.env['ir.attachment'].create({
            'name': 'mx-secret.txt', 'raw': b'mx secret', 'res_model': 'res.partner', 'res_id': hidden.id})
        self.env.flush_all()

    def test_messages_of_a_restricted_record_are_not_returned(self):
        self._chatter_of_the_hidden_partner()
        restrictions = {'res.partner': PARTNER_FILTER}
        domain = [('model', '=', 'res.partner'), ('res_id', '=', self.hidden.id)]
        baseline, restricted = self._parity(
            lambda: self._call('mail.message', 'search_read', [domain, ['body']]), restrictions)
        self.assertTrue(baseline)
        self.assertFalse(restricted)
        self._parity(lambda: self._call('mail.message', 'search_count', [domain]), restrictions)
        self._parity(lambda: self._call('res.partner', 'read', [self.hidden.ids, ['message_ids']]), restrictions)
        self._parity(lambda: self._as_user('mail.message').search(domain).ids, restrictions)
        self._parity(lambda: self._call('mail.message', 'formatted_read_group', [], {
            'domain': domain, 'groupby': ['model'], 'aggregates': ['__count']}), restrictions)

    def test_followers_of_a_restricted_record_are_not_returned(self):
        self._chatter_of_the_hidden_partner()
        domain = [('res_model', '=', 'res.partner'), ('res_id', '=', self.hidden.id)]
        baseline, _restricted = self._parity(
            lambda: self._call('mail.followers', 'search_read', [domain, ['partner_id']]),
            {'res.partner': PARTNER_FILTER}, changes=False)
        self.assertTrue(baseline)
        self._parity(lambda: self._call('res.partner', 'read', [self.hidden.ids, ['message_follower_ids']]),
                     {'res.partner': PARTNER_FILTER})

    def test_activities_of_a_restricted_record_are_not_returned(self):
        self._chatter_of_the_hidden_partner()
        domain = [('res_model', '=', 'res.partner'), ('res_id', '=', self.hidden.id)]
        baseline, restricted = self._parity(
            lambda: self._call('mail.activity', 'search_read', [domain, ['summary']]), {'res.partner': PARTNER_FILTER})
        self.assertTrue(baseline)
        self.assertFalse(restricted)
        self._parity(lambda: self._call('mail.activity', 'search_count', [domain]), {'res.partner': PARTNER_FILTER})
        self._parity(lambda: self._call('res.partner', 'read', [self.hidden.ids, ['activity_ids']]),
                     {'res.partner': PARTNER_FILTER})

    def test_attachments_of_a_restricted_record_are_not_returned(self):
        self._chatter_of_the_hidden_partner()
        restrictions = {'res.partner': PARTNER_FILTER}
        domain = [('res_model', '=', 'res.partner'), ('res_id', '=', self.hidden.id)]
        baseline, restricted = self._parity(
            lambda: self._call('ir.attachment', 'search_read', [domain, ['name']]), restrictions)
        self.assertTrue(baseline)
        self.assertFalse(restricted)
        self._parity(lambda: self._call('ir.attachment', 'read', [self.attachment.ids, ['name']]), restrictions)
        self._parity(lambda: self._as_user('ir.attachment').search(domain).ids, restrictions)
        self._parity(lambda: self._call('res.partner', 'read', [self.hidden.ids, ['message_attachment_count']]),
                     restrictions)

    @mute_logger('odoo.http')
    def test_files_and_images_of_a_restricted_record_are_not_served(self):
        self._chatter_of_the_hidden_partner()

        def fetch(url):
            response = self.url_open(url)
            return response.status_code, hashlib.md5(response.content).hexdigest()

        for url in (f'/web/content/{self.attachment.id}', f'/web/content/res.partner/{self.hidden.id}/image_128',
                    f'/web/image/res.partner/{self.hidden.id}/image_128',
                    f'/web/image/res.partner/{self.hidden.id}/image_1920'):
            with self.subTest(url=url):
                self._parity(lambda: fetch(url), {'res.partner': PARTNER_FILTER})

    def test_the_sale_order_count_of_a_partner_is_like_core(self):
        customer = self.env['res.partner'].create({'name': 'MX Customer'})
        self.env['sale.order'].create([
            {'partner_id': customer.id, 'client_order_ref': ref} for ref in (False, False, 'mx-hidden')])
        baseline, restricted = self._parity(
            lambda: self._as_user('res.partner').browse(customer.id).read(['sale_order_count'])[0]['sale_order_count'],
            {'sale.order': "[('client_order_ref', '!=', 'mx-hidden')]"})
        self.assertEqual((baseline, restricted), (3, 2))

    def test_the_total_invoiced_of_a_partner_is_like_core(self):
        self._need('account.move')
        customer = self.env['res.partner'].create({'name': 'MX Invoiced'})
        self.env['account.move'].create([{
            'move_type': 'out_invoice', 'partner_id': customer.id, 'ref': ref, 'invoice_date': '2026-10-01',
            'invoice_line_ids': [Command.create({'name': 'MX line', 'price_unit': 100.0, 'quantity': 1})],
        } for ref in (False, 'mx-hidden')]).action_post()
        self._parity(
            lambda: self._as_user('res.partner').browse(customer.id).read(['total_invoiced'])[0]['total_invoiced'],
            {'account.move': "[('ref', '!=', 'mx-hidden')]"}, changes=False)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixHiddenRelations(RelationCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._need('res.partner', 'sale.order', 'product.product')
        Partner = cls.env['res.partner']
        cls.secret = Partner.create({
            'name': 'MX Secret Contact', 'email': SECRET_EMAIL, 'phone': SECRET_PHONE, 'image_1920': png()})
        cls.parent = Partner.create({'name': 'MX Parent', 'email': 'mx-parent@example.com'})
        cls.child = Partner.create({'name': 'MX Child', 'parent_id': cls.parent.id, 'email': SECRET_EMAIL})
        cls.other.partner_id.write({'email': 'mx-other-secret@example.com', 'phone': '+995 555 222 333'})
        cls.product = cls.env['product.product'].create({
            'name': 'MX Costly', 'standard_price': 42.0, 'list_price': 99.0, 'barcode': 'MX-BARCODE-1'})
        cls.order = cls.env['sale.order'].create({'partner_id': cls.secret.id, 'order_line': [
            Command.create({'product_id': cls.product.id, 'product_uom_qty': 3, 'price_unit': 10.0})]})
        cls.line = cls.order.order_line

    def test_a_hidden_partner_email_is_blank_through_the_user(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        for method in ('read', 'web_read'):
            self.assertEqual(self._value(self.control, 'res.users', self.other, 'email', method),
                             'mx-other-secret@example.com')
            self.assertFalse(self._value(self.user, 'res.users', self.other, 'email', method))

    @mute_logger('odoo.http')
    def test_a_hidden_partner_email_cannot_find_the_user(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        with self.assertRaises(JsonRpcException) as caught:
            self._call('res.users', 'search_read', [[('email', '=', 'mx-other-secret@example.com')], ['id']])
        self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')

    def test_a_line_on_the_copy_wins_over_the_hidden_original(self):
        self._profile(fields=[*self._hide(('res.partner', 'email')), self._field_line('res.users', 'email', 'keep')])
        for method in ('read', 'web_read'):
            self.assertEqual(self._value(self.user, 'res.users', self.other, 'email', method),
                             'mx-other-secret@example.com')

    @mute_logger('odoo.http')
    def test_no_export_on_the_partner_email_holds_on_the_user_email(self):
        (self.user | self.control).group_ids = [Command.link(self.env.ref('base.group_allow_export').id)]
        self._profile(fields=[self._field_line('res.partner', 'email', 'keep', no_export=True)])
        self.authenticate(self.control.login, self.password)
        described = self._call('res.users', 'fields_get', [['email'], ['exportable']])
        self.assertTrue(described['email']['exportable'])
        self._call('res.users', 'export_data', [self.other.ids, ['email']])
        self.authenticate(self.user.login, self.password)
        described = self._call('res.users', 'fields_get', [['email'], ['exportable']])
        self.assertFalse(described['email']['exportable'])
        with self.assertRaises(JsonRpcException) as caught:
            self._call('res.users', 'export_data', [self.other.ids, ['email']])
        self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')

    def test_a_hidden_partner_email_is_blank_on_the_resource_through_the_user_email(self):
        self._need('resource.resource')
        resource = self.env['resource.resource'].create({'name': 'MX Resource', 'user_id': self.other.id})
        self._assert_not_leaked([('res.partner', 'email')], 'resource.resource', resource, 'email',
                                'mx-other-secret@example.com')

    def test_two_sources_reaching_one_copy_keep_the_stronger_mode(self):
        """ A copy reached from a read-only field and from a hidden one (a switch) is hidden. No such pair exists in
        the registry, so the copies of the two sources are given by hand. """
        phone, cost, copy = ('res.partner', 'phone'), ('product.template', 'standard_price'), ('res.users', 'phone')
        profile = self._profile(fields=[self._field_line(*phone, 'readonly')], hide_costs=True)
        copies = {phone: (cost, copy), cost: (copy,)}
        with patch.object(self.registry['gec.access.profile'], '_gec_field_copies', lambda self: copies):
            rules = profile._build_rules(self.user)
        self.assertEqual(rules.field_mode(*cost), 'hide')
        self.assertEqual(rules.field_mode(*copy), 'hide')

    def test_a_read_only_version_wage_is_not_written_through_the_employee(self):
        self._need('hr.version')
        if 'wage' not in self.env['hr.employee']._fields:
            self.skipTest("hr.employee carries no wage here")
        xmlids = ['hr.group_hr_manager', *(self.env['hr.version']._fields['wage'].groups or '').split(',')]
        (self.user | self.control).group_ids = [
            Command.link(self.env.ref(xmlid.strip()).id) for xmlid in xmlids if xmlid.strip()]
        employee = self.env['hr.employee'].create({'name': 'MX Paid', 'wage': 3210.0})
        self._profile(fields=[self._field_line('hr.version', 'wage', 'readonly')])
        self.authenticate(self.control.login, self.password)
        self._call('hr.employee', 'write', [employee.ids, {'wage': 4000.0}])
        self.authenticate(self.user.login, self.password)
        self._call('hr.employee', 'write', [employee.ids, {'wage': 5000.0}])
        employee.invalidate_recordset()
        self.assertEqual(employee.wage, 4000.0)

    def _search_fields(self, arch):
        """ {field name: filter_domain} of the field nodes of a search arch. """
        return {node.get('name'): node.get('filter_domain') for node in etree.fromstring(arch).iter('field')}

    @mute_logger('odoo.http')
    def test_the_user_search_view_does_not_search_a_hidden_email(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        views = {}
        for user in (self.control, self.user):
            self.authenticate(user.login, self.password)
            views[user] = self._call('res.users', 'get_views', [[[False, 'search']]])['views']['search']['arch']
        self.assertIn('email', self._search_fields(views[self.control])['name'])
        self.assertFalse(self._search_fields(views[self.user])['name'])
        # the client searches the remaining field on its own name; the domain of the full text search is refused
        found = self._call('res.users', 'web_search_read', [], {
            'domain': [('name', 'ilike', 'mx_rel')], 'specification': {'name': {}}})
        self.assertTrue(found['records'])
        with self.assertRaises(JsonRpcException) as caught:
            self._call('res.users', 'web_search_read', [], {
                'domain': ['|', ('name', 'ilike', 'mx_rel'), ('email', 'ilike', 'mx_rel')], 'specification': {'id': {}}})
        self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')

    def test_a_search_field_or_progress_bar_on_a_hidden_field_is_left_out_of_a_view(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        Profile = self.env['gec.access.profile'].with_user(self.user)
        rules = Profile._current_rules()
        search = etree.fromstring("""<search>
            <field name="name" filter_domain="[('parent_id.email', 'ilike', self)]"/>
            <field name="ref" filter_domain="[('name', 'ilike', self)]"/>
        </search>""")
        Profile._apply_view_rules(rules, search, 'res.partner', 'search')
        self.assertEqual([(node.get('name'), node.get('filter_domain')) for node in search.iter('field')],
                         [('name', None), ('ref', "[('name', 'ilike', self)]")])
        kanban = etree.fromstring("""<kanban>
            <progressbar field="activity_state" colors="{}" sum_field="email"/>
        </kanban>""")
        Profile._apply_view_rules(rules, kanban, 'res.partner', 'kanban')
        self.assertEqual([dict(node.attrib) for node in kanban.iter('progressbar')],
                         [{'field': 'activity_state', 'colors': '{}'}])
        kanban = etree.fromstring("""<kanban><progressbar field="email" colors="{}"/></kanban>""")
        Profile._apply_view_rules(rules, kanban, 'res.partner', 'kanban')
        self.assertFalse(list(kanban.iter('progressbar')))

    def test_the_cost_is_never_returned_by_the_variant_or_the_template(self):
        self._profile(hide_costs=True)
        for model, record in (('product.product', self.product), ('product.template', self.product.product_tmpl_id)):
            for method in ('read', 'web_read'):
                with self.subTest(model=model, method=method):
                    self.assertEqual(self._value(self.control, model, record, 'standard_price', method), 42.0)
                    self.assertFalse(self._value(self.user, model, record, 'standard_price', method))

    def test_the_cost_is_blank_when_read_through_a_nested_relation(self):
        self._profile(hide_costs=True)
        specs = (
            ('product.product', self.product, {'product_tmpl_id': {'fields': {'standard_price': {}}}},
             lambda row: row['product_tmpl_id']['standard_price']),
            ('product.template', self.product.product_tmpl_id,
             {'product_variant_ids': {'fields': {'standard_price': {}}}},
             lambda row: row['product_variant_ids'][0]['standard_price']),
            ('sale.order.line', self.line, {'product_id': {'fields': {'standard_price': {}}}},
             lambda row: row['product_id']['standard_price']),
            ('sale.order.line', self.line, {'product_template_id': {'fields': {'standard_price': {}}}},
             lambda row: row['product_template_id']['standard_price']),
            ('sale.order', self.order, {'order_line': {'fields': {'product_id': {'fields': {'standard_price': {}}}}}},
             lambda row: row['order_line'][0]['product_id']['standard_price']),
        )
        for model, record, spec, pick in specs:
            with self.subTest(model=model, spec=spec):
                self.authenticate(self.control.login, self.password)
                self.assertEqual(pick(self._call(model, 'web_read', [record.ids], {'specification': spec})[0]), 42.0)
                self.authenticate(self.user.login, self.password)
                self.assertFalse(pick(self._call(model, 'web_read', [record.ids], {'specification': spec})[0]))

    def test_the_cost_of_a_sale_line_is_blank(self):
        self._profile(hide_costs=True)
        for name in ('purchase_price', 'margin', 'margin_percent'):
            with self.subTest(field=name):
                self.assertTrue(self._value(self.control, 'sale.order.line', self.line, name))
                self.assertFalse(self._value(self.user, 'sale.order.line', self.line, name))

    @mute_logger('odoo.http')
    def test_the_cost_cannot_be_searched_or_grouped(self):
        self._profile(hide_costs=True)
        calls = (
            ('product.product', 'search_read', [[('standard_price', '>', 0)], ['name']], {}),
            ('product.product', 'search_read', [[('product_tmpl_id.standard_price', '>', 0)], ['name']], {}),
            ('product.template', 'search_count', [[('standard_price', '>', 0)]], {}),
            ('product.product', 'search_read', [[], ['name']], {'order': 'standard_price desc'}),
            ('product.product', 'formatted_read_group', [], {
                'domain': [], 'groupby': ['categ_id'], 'aggregates': ['standard_price:avg']}),
            ('sale.order.line', 'search_read', [[('product_id.standard_price', '>', 0)], ['name']], {}),
        )
        for model, method, args, kwargs in calls:
            with self.subTest(model=model, method=method, args=args, kwargs=kwargs):
                self.authenticate(self.control.login, self.password)
                self._call(model, method, args, kwargs)
                self.authenticate(self.user.login, self.password)
                with self.assertRaises(JsonRpcException) as caught:
                    self._call(model, method, args, kwargs)
                self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')

    def test_follower_email_over_a_hidden_partner_email(self):
        self._need('mail.followers')
        document = self.env['res.partner'].create({'name': 'MX Followed'})
        document.message_subscribe(partner_ids=self.secret.ids)
        follower = document.message_follower_ids.filtered(lambda line: line.partner_id == self.secret)
        self._assert_not_leaked([('res.partner', 'email')], 'mail.followers', follower, 'email', SECRET_EMAIL)

    def _attendee(self):
        self._need('calendar.attendee')
        event = self.env['calendar.event'].create({
            'name': 'MX Meeting', 'start': '2026-10-27 09:00:00', 'stop': '2026-10-27 10:00:00',
            'partner_ids': [Command.set(self.secret.ids)]})
        return event.attendee_ids.filtered(lambda line: line.partner_id == self.secret)

    def test_attendee_email_over_a_hidden_partner_email(self):
        self._assert_not_leaked([('res.partner', 'email')], 'calendar.attendee', self._attendee(), 'email',
                                SECRET_EMAIL)

    def test_attendee_phone_over_a_hidden_partner_phone(self):
        self._assert_not_leaked([('res.partner', 'phone')], 'calendar.attendee', self._attendee(), 'phone',
                                SECRET_PHONE)

    def test_sale_line_unit_cost_over_hidden_costs(self):
        if 'unit_cost' not in self.env['sale.order.line']._fields:
            self.skipTest("unit_cost needs sale_account_accountant")
        self._assert_not_leaked([], 'sale.order.line', self.line, 'unit_cost', 42.0, hide_costs=True)

    def _assert_still_returned(self, model, record, field, secret=None, **profile_values):
        """ Both the control user and the user whose profile hides the prices get ``record.field`` (any value when
        ``secret`` is None). """
        self._profile(**profile_values)
        for method in ('read', 'web_read'):
            for user in (self.control, self.user):
                with self.subTest(model=model, field=field, method=method, user=user.login):
                    value = self._value(user, model, record, field, method)
                    if secret is None:
                        self.assertTrue(value)
                    else:
                        self.assertEqual(value, secret)

    def test_accepted_limit_sale_line_untaxed_amount_to_invoice_over_hidden_prices(self):
        """ Accepted limit (D8): a computed field built on a hidden field is not covered, as in standard Odoo. """
        self.order.action_confirm()
        self._assert_still_returned('sale.order.line', self.line, 'untaxed_amount_to_invoice', 30.0,
                                    hide_sale_prices=True)

    def test_accepted_limit_sale_line_amount_to_invoice_over_hidden_prices(self):
        """ Accepted limit (D8): a computed field built on a hidden field is not covered, as in standard Odoo. """
        self.order.action_confirm()
        self._assert_still_returned('sale.order.line', self.line, 'amount_to_invoice', None, hide_sale_prices=True)

    def test_combo_item_price_over_hidden_prices(self):
        self._need('product.combo.item')
        combo = self.env['product.combo'].create({
            'name': 'MX Combo', 'combo_item_ids': [Command.create({'product_id': self.product.id})]})
        self._assert_not_leaked([], 'product.combo.item', combo.combo_item_ids, 'lst_price', 99.0,
                                hide_sale_prices=True)

    def test_move_line_barcode_over_a_hidden_product_barcode(self):
        self._need('stock.move.line')
        if 'product_barcode' not in self.env['stock.move.line']._fields:
            self.skipTest("product_barcode needs stock_barcode")
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        line = self.env['stock.move.line'].create({
            'product_id': self.product.id, 'quantity': 1, 'company_id': warehouse.company_id.id,
            'location_id': warehouse.lot_stock_id.id, 'location_dest_id': self.env.ref('stock.stock_location_customers').id})
        self._assert_not_leaked([('product.product', 'barcode')], 'stock.move.line', line, 'product_barcode',
                                'MX-BARCODE-1')

    def test_employee_email_over_a_hidden_user_email(self):
        self._need('hr.employee')
        employee = self.env['hr.employee'].create({'name': 'MX Employee', 'user_id': self.other.id})
        self._assert_not_leaked([('res.users', 'email')], 'hr.employee', employee, 'email',
                                'mx-other-secret@example.com')

    def test_employee_phone_over_a_hidden_user_phone(self):
        self._need('hr.employee')
        employee = self.env['hr.employee'].create({'name': 'MX Employee', 'user_id': self.other.id})
        self._assert_not_leaked([('res.users', 'phone')], 'hr.employee', employee, 'phone', '+995 555 222 333')

    def test_employee_wage_over_a_hidden_version_wage(self):
        self._need('hr.version')
        if 'wage' not in self.env['hr.employee']._fields:
            self.skipTest("hr.employee carries no wage here")
        employee = self.env['hr.employee'].create({'name': 'MX Paid', 'wage': 3210.0})
        self._assert_not_leaked([('hr.version', 'wage')], 'hr.employee', employee, 'wage', 3210.0)

    def test_message_author_avatar_over_a_hidden_partner_avatar(self):
        document = self.env['res.partner'].create({'name': 'MX Posted'})
        message = document.message_post(
            body='MX note', author_id=self.secret.id, message_type='comment', subtype_xmlid='mail.mt_note')
        self._assert_not_leaked([('res.partner', 'avatar_128')], 'mail.message', message, 'author_avatar')

    def test_team_member_email_over_a_hidden_user_email(self):
        self._need('crm.team.member')
        team = self.env['crm.team'].create({'name': 'MX Team'})
        member = self.env['crm.team.member'].create({'user_id': self.other.id, 'crm_team_id': team.id})
        self._assert_not_leaked([('res.users', 'email')], 'crm.team.member', member, 'email',
                                'mx-other-secret@example.com')

    def test_resource_email_over_a_hidden_user_email(self):
        self._need('resource.resource')
        resource = self.env['resource.resource'].create({'name': 'MX Resource', 'user_id': self.other.id})
        self._assert_not_leaked([('res.users', 'email')], 'resource.resource', resource, 'email',
                                'mx-other-secret@example.com')

    @mute_logger('odoo.http')
    def test_a_hidden_field_in_a_related_domain_is_refused(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        secret = SECRET_EMAIL
        domains = (
            ('res.partner', [('parent_id.email', '=', secret)]),
            ('res.partner', [('child_ids', 'any', [('email', '=', secret)])]),
            ('res.partner', [('child_ids', 'not any', [('email', '=', secret)])]),
            ('res.partner', ['|', ('name', '=', 'MX'), ('parent_id.email', 'ilike', 'mx-sec')]),
            ('res.partner', [('parent_id', 'any', [('child_ids', 'any', [('email', '=', secret)])])]),
            ('sale.order', [('partner_id.email', '=', secret)]),
            ('sale.order', [('partner_id', 'any', [('email', '=', secret)])]),
            ('sale.order', [('order_line', 'any', [('order_partner_id.email', '=', secret)])]),
            ('sale.order.line', [('order_id.partner_id.email', '=', secret)]),
        )
        calls = (
            ('search_read', lambda domain: ([domain, ['name']], {})),
            ('search', lambda domain: ([domain], {})),
            ('search_count', lambda domain: ([domain], {})),
            ('web_search_read', lambda domain: ([], {'domain': domain, 'specification': {'id': {}}})),
            ('formatted_read_group', lambda domain: ([], {'domain': domain, 'groupby': [], 'aggregates': ['__count']})),
            ('read_group', lambda domain: ([], {'domain': domain, 'groupby': [], 'aggregates': ['__count']})),
            ('name_search', lambda domain: ([], {'domain': domain})),
        )
        for model, domain in domains:
            for method, arguments in calls:
                args, kwargs = arguments(domain)
                with self.subTest(model=model, domain=domain, method=method):
                    self.authenticate(self.control.login, self.password)
                    self._call(model, method, args, kwargs)
                    self.authenticate(self.user.login, self.password)
                    with self.assertRaises(JsonRpcException) as caught:
                        self._call(model, method, args, kwargs)
                    self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')

    @mute_logger('odoo.http')
    def test_a_hidden_field_in_a_related_order_is_refused(self):
        self._profile(fields=self._hide(('res.partner', 'email')))
        for model, order in (('res.partner', 'parent_id.email'), ('sale.order', 'partner_id.email desc')):
            with self.subTest(model=model, order=order):
                with self.assertRaises(JsonRpcException) as caught:
                    self._call(model, 'search_read', [[], ['name']], {'order': order})
                self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError')
