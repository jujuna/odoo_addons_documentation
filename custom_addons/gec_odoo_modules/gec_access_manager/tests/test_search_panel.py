# The search panel reads the values of a relational field on its own model (search_read under the panel's
# call): what the client sends about that model, and about this one, is checked like a search of the client.
import json

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSearchPanel(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'sale.order.line' not in cls.env or 'purchase_price' not in cls.env['sale.order.line']._fields:
            cls.skipTest(cls, "the search panel tests need sale_margin")
        cls.password = 'gec-access-manager-panel-pw'
        groups = 'base.group_user,sales_team.group_sale_salesman'
        cls.member = new_test_user(cls.env, 'gec_panel_member', groups=groups, password=cls.password)
        cls.plain = new_test_user(cls.env, 'gec_panel_plain', groups=groups, password=cls.password)
        cls.env['gec.access.profile'].create({
            'name': 'Panel costs', 'hide_costs': True, 'user_ids': [Command.set(cls.member.ids)],
            'field_ids': [Command.create({
                'model_id': cls.env['ir.model']._get('product.category').id,
                'field_id': cls.env['ir.model.fields']._get('product.category', 'parent_id').id,
                'mode': 'hide',
            })],
        })
        cls.env['gec.access.profile'].create({
            'name': 'Panel plain', 'block_export': True, 'user_ids': [Command.set(cls.plain.ids)]})
        cls.product = cls.env['product.product'].create({'name': 'Panel Product', 'standard_price': 777})

    def _panel(self, method, field_name, model='sale.order.line', **kwargs):
        return self.make_jsonrpc_request(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': [field_name], 'kwargs': kwargs})

    def _multi(self, **kwargs):
        return self._panel('search_panel_select_multi_range', 'product_id', expand=True, **kwargs)

    def _assert_refused(self, call, **kwargs):
        with mute_logger('odoo.http'), self.assertRaises(JsonRpcException) as caught:
            call(**kwargs)
        self.assertEqual(str(caught.exception), 'odoo.exceptions.AccessError', kwargs)

    def test_a_hidden_field_of_the_values_is_refused(self):
        self.authenticate(self.member.login, self.password)
        self._assert_refused(self._multi, group_by='standard_price')
        self._assert_refused(self._multi, comodel_domain=[('standard_price', '>', 500)])
        self._assert_refused(self._multi, group_by='categ_id', enable_counters=True,
                             group_domain={json.dumps(1): [('purchase_price', '>', 0)]})
        self._assert_refused(self._multi, enable_counters=True, group_domain=[('purchase_price', '>', 0)])

    def test_a_panel_without_a_hidden_field_works(self):
        self.authenticate(self.member.login, self.password)
        values = self._multi(group_by='categ_id')['values']
        self.assertIn(self.product.id, [value['id'] for value in values])

    def test_a_user_without_the_rule_gets_the_values(self):
        self.authenticate(self.plain.login, self.password)
        values = {value['id']: value for value in self._multi(group_by='standard_price')['values']}
        self.assertEqual(values[self.product.id]['group_id'], 777)

    def test_a_tree_of_values_with_a_hidden_parent_is_shown_flat(self):
        self.authenticate(self.member.login, self.password)
        result = self._panel('search_panel_select_range', 'categ_id', model='product.template')
        self.assertFalse(result['parent_field'])
        self.assertTrue(all('parent_id' not in value for value in result['values']))
        self.authenticate(self.plain.login, self.password)
        result = self._panel('search_panel_select_range', 'categ_id', model='product.template')
        self.assertEqual(result['parent_field'], 'parent_id')
