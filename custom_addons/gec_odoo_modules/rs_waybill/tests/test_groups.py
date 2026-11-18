"""Waybill User and Waybill Manager: Users work with waybills; only Managers change the excise code
list and delete mappings; every internal user can read waybills.
"""

from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestGroups(RsWaybillCommon):

    def _user(self, login, *groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'group_ids': [(6, 0, [self.env.ref(g).id for g in ('base.group_user',) + groups])]})

    def test_inventory_sales_and_purchase_users_are_waybill_users(self):
        for group in ('stock.group_stock_user', 'sales_team.group_sale_salesman',
                      'purchase.group_purchase_user'):
            with self.subTest(group=group):
                self.assertTrue(self._user('u_' + group, group).has_group('rs_waybill.group_waybill_user'))

    def test_administrators_are_managers(self):
        self.assertTrue(self.env.ref('base.user_admin').has_group('rs_waybill.group_waybill_manager'))

    def test_any_internal_user_can_read_but_not_create_waybills(self):
        plain = self._user('plain')
        waybill = self.make_waybill()
        waybill.with_user(plain).read(['state'])
        with self.assertRaises(AccessError):
            self.env['rs.waybill'].with_user(plain).create({'waybill_type': '2'})

    def test_waybill_user_works_with_waybills_but_not_the_excise_list(self):
        user = self._user('wb_user', 'rs_waybill.group_waybill_user')
        self.env['rs.waybill'].with_user(user).with_context(rs_skip_resolve=True).create({'waybill_type': '2'})
        with self.assertRaises(AccessError):
            self.env['rs.excise.code'].with_user(user).create({'rs_id': 1, 'name': 'Test', 'active_from': '2026-01-01'})

    def test_only_a_manager_deletes_a_product_mapping(self):
        partner = self.env['res.partner'].create({'name': 'V'})
        ref = self.env['rs.product.external.ref'].create({
            'seller_partner_id': partner.id, 'external_barcode': 'B1',
            'product_id': self.product.product_tmpl_id.id})
        user = self._user('wb_user2', 'rs_waybill.group_waybill_user')
        with self.assertRaises(AccessError):
            ref.with_user(user).unlink()
        ref.with_user(self._user('wb_mgr', 'rs_waybill.group_waybill_manager')).unlink()

    def test_the_waybills_menu_is_for_waybill_users(self):
        self.assertIn(self.env.ref('rs_waybill.group_waybill_user'),
                      self.env.ref('rs_waybill.menu_rs_waybill_root').group_ids)
