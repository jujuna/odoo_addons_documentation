"""The rs.ge Inbox: search rows land on the right vendor, and a correction cannot be imported
before its original."""

from datetime import date

from odoo.tests import tagged

from . import stub_responses
from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestBuyerInbox(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})

    def _row(self, rs_id, status, k_id=-1, k_type=0):
        return {
            'id': rs_id, 'status': status, 'saident_no_s': '404404404', 'org_name': 'Supplier LLC',
            'buyer_un_id': 731937, 'k_id': k_id, 'k_type': k_type, 'tanxa': 118.0,
            'f_series': 'AA', 'f_number': str(rs_id), 'operation_dt': '2026-09-20T00:00:00',
            'reg_dt': '2026-09-20T10:00:00',
        }

    def _search(self, rows):
        wizard = self.env['rs.einvoice.inbox.wizard'].with_company(self.company).create({
            'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 30)})
        with self._patch_rsge(
            chek=stub_responses.chek(),
            get_buyer_invoices=stub_responses.datatable('get_buyer_invoices', rows),
        ) as rsge:
            wizard.action_search()
            self.assertEqual(rsge.calls, ['chek', 'get_buyer_invoices'])
        return wizard

    def test_search_matches_the_vendor_by_tin(self):
        wizard = self._search([self._row(555001, 1)])
        self.assertEqual(len(wizard.line_ids), 1)
        line = wizard.line_ids
        self.assertEqual(line.partner_id, self.vendor)
        self.assertTrue(line.selected)
        self.assertFalse(line.already_imported)

    def test_correction_without_its_original_is_refused(self):
        wizard = self._search([self._row(555002, 5, k_id=999999, k_type=1)])
        line = wizard.line_ids
        with self._patch_rsge(chek=stub_responses.chek()):
            wizard.action_import_selected()
        self.assertEqual(line.import_status, 'error')
        self.assertIn('Import the original first', line.import_note)
        self.assertFalse(self.env['account.move'].search([('rs_einv_id', '=', '555002')]))
