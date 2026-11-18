"""A received vendor waybill whose receipt Odoo cannot book yet (PO awaiting approval) keeps every update from RS.GE:
the receipt waits under a banner, said once in the chatter, and the drift job books it once the PO is approved."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestReceiptNotBookable(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        vendor = self.env['res.partner'].create({'name': 'Vendor LLC', 'vat': '404040404'})
        self.po = self.env['purchase.order'].create({'partner_id': vendor.id})  # draft: not approved yet
        self.waybill = self.make_waybill(waybill_direction='buyer', state='active', waybill_status='1',
                                         rs_internal_id=996001, seller_tin=vendor.vat,
                                         purchase_id=self.po.id)
        self.env['rs.waybill'].search([('id', '!=', self.waybill.id)]).write(
            {'rs_drifted_checked': '2000-01-01 00:00:00'})

    def _drift(self, rs_vals):
        """One drift pass in which RS.GE reports rs_vals for this waybill."""
        Waybill = type(self.env['rs.waybill'])
        with patch.object(type(self.env['rs.waybill.soap.service']), 'get_full_waybill',
                          return_value=({'ID': '996001'}, [])), \
                patch.object(Waybill, '_map_rs_waybill_vals', return_value=rs_vals), \
                patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=float('inf')):
            self.env['rs.waybill']._cron_rs_drift_repair_one()

    def _messages(self):
        return self.waybill.message_ids.filtered(lambda m: 'Validate the incoming receipt' in (m.body or ''))

    def test_the_update_is_kept_and_the_receipt_waits(self):
        self._drift({'is_confirmed': '1'})

        self.assertEqual(self.waybill.is_confirmed, '1', "the RS.GE update is not rolled back")
        self.assertIn('not confirmed', self.waybill.rs_post_commit_error)
        self.assertEqual(len(self._messages()), 1)

        self._drift({'is_confirmed': '1'})
        self.assertEqual(len(self._messages()), 1, "the same failure is not posted again")

    def test_a_later_cancel_still_reaches_odoo(self):
        self._drift({'is_confirmed': '1'})
        self._drift({'state': 'cancelled', 'waybill_status': '-2'})
        self.assertEqual(self.waybill.state, 'cancelled')

    def test_once_approved_the_drift_job_books_it(self):
        flour = self.env['product.product'].create({'name': 'Flour', 'is_storable': True})
        self.po.order_line = [(0, 0, {'product_id': flour.id, 'product_qty': 10, 'price_unit': 2.0})]
        self.add_line(self.waybill, quantity=10, unit_price=2.0, product_id=flour.id)
        with patch.object(type(self.env['rs.waybill']), '_goods_lines_changed', return_value=False):
            self._drift({'is_confirmed': '1'})
            self.assertTrue(self.waybill.rs_post_commit_error)

            self.po.button_confirm()  # the manager approves
            self._drift({})

        self.assertFalse(self.waybill.rs_post_commit_error, "banner gone")
        self.assertEqual(flour.qty_available, 10)
