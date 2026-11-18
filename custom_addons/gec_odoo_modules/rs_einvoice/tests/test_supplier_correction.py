"""A supplier correction imported on a vendor bill keeps the original live until the correction is accepted on
rs.ge (status 8); a rejected correction leaves the original as it was."""

from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged

from .common import RsEinvoiceCommon

ORIGINAL, CORRECTION = 555400, 555401


class FakeRsge:
    """rs.ge holding an original bill and its supplier correction, answering per rs.ge ID."""

    def __init__(self, correction_status):
        self.status = {ORIGINAL: '3', CORRECTION: correction_status}

    def _check_auth(self):
        return None

    def _rs_partner_un_id(self, partner):
        return 1149251

    def _rs_company_un_id(self):
        return 731937

    def get_invoice(self, inv_id):
        return SimpleNamespace(
            status=self.status[inv_id], k_id=ORIGINAL if inv_id == CORRECTION else -1, k_type=3,
            seller_un_id=1149251, buyer_un_id=731937, f_series='AB', f_number=str(inv_id),
            was_ref=False, operation_dt=None, seq_num_s='', seq_num_b='')

    def get_makoreqtirebeli(self, inv_id):
        return 0

    def get_invoice_desc(self, inv_id):
        return [{'id': inv_id * 10, 'goods': 'Cement', 'g_unit': 'ერთეული', 'g_number': 2,
                 'full_amount': 90.0 if inv_id == CORRECTION else 100.0, 'drg_amount': 0.0}]

    def buyer_accept_invoice(self, inv_id, target_status):
        self.status[inv_id] = str(target_status)
        return SimpleNamespace(acsept_invoice_statusResult=True)

    def buyer_reject_invoice(self, inv_id, reason):
        self.status[inv_id] = {'1': '0', '5': '4'}[self.status[inv_id]]
        return SimpleNamespace(ref_invoice_statusResult=True)


@tagged('post_install', '-at_install')
class TestSupplierCorrection(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})

    def _imported(self, correction_status, invoice_date=None):
        """Post an accepted bill, import its supplier correction at ``correction_status``; return (bill, copy, rs.ge)."""
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'invoice_date': invoice_date or fields.Date.today(),
            'rs_einv_id': str(ORIGINAL),
            'rs_einv_status': '2',
            'invoice_line_ids': [Command.create({'name': 'Cement', 'quantity': 2, 'price_unit': 50})],
        })
        bill.action_post()
        bill.rs_einv_supplier_k_id = str(CORRECTION)
        rsge = FakeRsge(correction_status)
        self.enterContext(patch.object(type(bill), '_rs_get_service', lambda move, check_auth=False: rsge))
        self.enterContext(patch.object(self.env.cr, 'commit', self.env.cr.flush))
        bill.action_rs_import_supplier_correction()
        return bill, bill.rs_einv_replaced_by_id, rsge

    def test_original_stays_live_until_the_correction_is_accepted(self):
        bill, copy, _rsge = self._imported('5')
        self.assertEqual(bill.state, 'posted')
        self.assertEqual((copy.state, copy.rs_einv_status, copy.rs_einv_replaces_id), ('draft', '5', bill))
        copy.action_rs_buyer_accept()
        self.assertEqual((copy.state, copy.rs_einv_status), ('posted', '8'))
        self.assertEqual(copy.amount_untaxed, 90)
        self.assertEqual(bill.state, 'cancel')

    def test_rejected_correction_leaves_the_original_live(self):
        bill, copy, _rsge = self._imported('5')
        self.env['rs.einvoice.reject.wizard'].create({'move_id': copy.id, 'reason': 'Wrong price'}).action_confirm()
        self.assertEqual((copy.state, copy.rs_einv_status), ('cancel', '4'))
        self.assertEqual(bill.state, 'posted')

    def test_correction_already_accepted_cancels_the_original_on_import(self):
        bill, copy, _rsge = self._imported('8')
        self.assertEqual(bill.state, 'cancel')
        self.assertEqual((copy.state, copy.rs_einv_status), ('draft', '8'))
        self.assertEqual(len(copy.activity_ids.filtered(lambda activity: activity.summary == 'Post the corrected bill')), 1)

    def test_correction_already_accepted_on_a_bill_of_an_earlier_month_reverses_it(self):
        bill, copy, _rsge = self._imported('8', invoice_date=fields.Date.subtract(fields.Date.today(), months=2))
        todo = copy.activity_ids.filtered(lambda activity: activity.summary == 'Post the corrected bill')
        self.assertEqual(bill.state, 'posted')
        self.assertTrue(bill.reversal_move_ids)
        self.assertEqual(len(todo), 1)
        self.assertIn('cancelled or reversed', todo.note)

    def test_correction_is_dated_the_day_it_is_posted(self):
        bill, copy, _rsge = self._imported('8')
        copy.date = fields.Date.subtract(fields.Date.today(), months=2)
        copy.action_post()
        self.assertEqual((copy.state, copy.date), ('posted', fields.Date.context_today(copy)))
