"""Send to RS and Send to buyer, against recorded rs.ge replies."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from . import stub_responses
from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestSellerFlow(RsEinvoiceCommon):

    def _line_rows(self):
        """The one line of _invoice() as rs.ge lists it after the sync."""
        return [{
            'ID': 800001, 'INV_ID': 700123, 'GOODS': 'Service', 'G_UNIT': 'ერთეული',
            'G_NUMBER': 2, 'FULL_AMOUNT': 118.0, 'DRG_AMOUNT': 18.0, 'VAT_TYPE': 0,
        }]

    def test_create_then_send(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        with self._patch_rsge(
            chek=stub_responses.chek(),
            get_un_id_from_tin=stub_responses.get_un_id_from_tin(),
            save_invoice=stub_responses.save_invoice(invois_id=700123),
            get_invoice_desc=[
                stub_responses.datatable('get_invoice_desc', []),
                stub_responses.datatable('get_invoice_desc', self._line_rows()),
            ],
            save_invoice_desc=stub_responses.save_invoice_desc(id=800001),
            change_invoice_status=stub_responses.change_invoice_status(),
            get_invoice=[
                stub_responses.get_invoice(status=0, f_series='', f_number=''),
                stub_responses.get_invoice(status=1, f_series='AA', f_number='12345'),
            ],
        ) as rsge:
            invoice.action_rs_create()
            self.assertEqual(invoice.rs_einv_id, '700123')
            self.assertEqual(invoice.rs_einv_status, '0')
            self.assertEqual(rsge.calls[:3], ['chek', 'get_un_id_from_tin', 'save_invoice'],
                             "identity comes from the stored taxpayer id, the buyer from the TIN")
            self.assertIn('save_invoice_desc', rsge.calls, "the line was pushed after the header")

            invoice.action_rs_send()
            self.assertEqual(invoice.rs_einv_status, '1')
            self.assertEqual(rsge.calls[-2:], ['change_invoice_status', 'get_invoice'],
                             "send is verified by reading the record back")

    def test_create_refused_when_rsge_rejects_credentials(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        with self._patch_rsge(chek=stub_responses.chek(result=False)):
            with self.assertRaises(UserError):
                invoice.action_rs_create()
        self.assertFalse(invoice.rs_einv_id)

    def test_buyer_taxpayer_id_is_cached_on_the_partner(self):
        self.customer.rs_un_id = 1149251
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        with self._patch_rsge(
            chek=stub_responses.chek(),
            save_invoice=stub_responses.save_invoice(invois_id=700124),
            get_invoice_desc=[
                stub_responses.datatable('get_invoice_desc', []),
                stub_responses.datatable('get_invoice_desc', self._line_rows()),
            ],
            save_invoice_desc=stub_responses.save_invoice_desc(id=800002),
        ) as rsge:
            invoice.action_rs_create()
        self.assertNotIn('get_un_id_from_tin', rsge.calls, "a known taxpayer id is not looked up again")
        self.customer.vat = '99999999999'
        self.assertFalse(self.customer.rs_un_id, "a new Tax ID drops the cached id")

    def test_create_refused_without_taxpayer_id(self):
        self.env.user.with_company(self.company).sudo().write({'rs_un_id': 0})
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        with self._patch_rsge(chek=stub_responses.chek()):
            with self.assertRaisesRegex(UserError, 'Test RS Credentials'):
                invoice.action_rs_create()

    def test_native_settlement_mode_without_downpayment_lines_does_not_block_sending(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20), rs_einv_advance_settlement_mode='native_attach')
        invoice.action_post()
        invoice._rs_validate()

    def test_goods_is_the_product_name_in_the_buyer_language(self):
        self.env['res.lang']._activate_lang('ka_GE')
        product = self.env['product.product'].create({'name': 'Cement M400', 'default_code': 'C400'})
        product.with_context(lang='ka_GE').name = 'ცემენტი M400'
        self.customer.lang = 'ka_GE'
        invoice = self._invoice()
        invoice.invoice_line_ids.product_id = product
        self.assertEqual(invoice.invoice_line_ids.rs_einv_goods, 'ცემენტი M400', "the buyer's language, without the internal reference")

    def test_parties_follow_the_current_company_and_partner(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        self.assertEqual((invoice.rs_einv_seller_tin, invoice.rs_einv_buyer_name), ('206322102', 'GE Customer'))
        self.customer.vat = '99999999999'
        self.company.name = 'Renamed Company'
        self.assertEqual((invoice.rs_einv_buyer_tin, invoice.rs_einv_seller_name), ('99999999999', 'Renamed Company'))

    def test_vendor_bill_has_the_partner_as_seller(self):
        bill = self._invoice(move_type='in_invoice')
        self.assertTrue(bill.rs_einv_is_buyer_side)
        self.assertEqual((bill.rs_einv_seller_tin, bill.rs_einv_buyer_tin), ('12345678910', '206322102'))
