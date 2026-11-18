"""Accept on rs.ge never posts lines the supplier changed on rs.ge after the bill took them, and the
accountant's own edits (taxes, extra lines) never block it."""

from unittest.mock import patch

from lxml import etree
from requests.exceptions import ReadTimeout

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from . import stub_responses
from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestBuyerAcceptLines(RsEinvoiceCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Supplier LLC', 'vat': '404404404'})
        cls.purchase_vat_18 = cls.env['account.tax'].create({
            'name': 'VAT 18% purchase', 'amount': 18, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id, 'ubl_cii_tax_category_code': 'S',
        })
        cls.purchase_vat_18_no_credit = cls.env['account.tax'].create({
            'name': 'VAT 18% purchase, no credit', 'amount': 18, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': cls.company.id, 'ubl_cii_tax_category_code': 'S',
        })
        cls.company.account_purchase_tax_id = cls.purchase_vat_18

    def _rsge(self, before, after=None, statuses=(1, 2)):
        """rs.ge holding one line, (quantity, full amount, VAT) ``before`` for the first line read, then ``after``;
        get_invoice answers ``statuses`` in call order."""
        def lines(qty, full, vat):
            return stub_responses.datatable('get_invoice_desc', [{
                'ID': 900001, 'INV_ID': 555300, 'GOODS': 'Cement', 'G_UNIT': 'ერთეული',
                'G_NUMBER': qty, 'FULL_AMOUNT': full, 'DRG_AMOUNT': vat, 'VAT_TYPE': 0 if vat else -1,
            }])
        return self._patch_rsge(
            chek=stub_responses.chek(),
            get_invoice=[stub_responses.get_invoice(status=s, seller_un_id=1149251, buyer_un_id=731937)
                         for s in statuses],
            get_makoreqtirebeli=stub_responses.envelope(
                'get_makoreqtirebeli', get_makoreqtirebeliResult=True, k_id=-1),
            get_invoice_desc=[lines(*before), lines(*(after or before))],
            acsept_invoice_status=stub_responses.envelope(
                'acsept_invoice_status', acsept_invoice_statusResult=True),
        )

    def _bill(self, lines=()):
        """A draft vendor bill at Sent (Pending), with hand-typed ``lines`` (quantity, price)."""
        return self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'invoice_date': '2026-09-20',
            'rs_einv_id': '555300',
            'rs_einv_status': '1',
            'invoice_line_ids': [Command.create({'name': 'Cement', 'quantity': qty, 'price_unit': price})
                                 for qty, price in lines],
        })

    def _import(self, bill):
        """Take rs.ge's lines into the bill, as Pull does."""
        bill._rs_refresh_pulled_lines(bill._rs_get_service())
        bill._rs_auto_import_pulled_to_bill_lines()

    def test_changed_lines_are_refused_until_reimported(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0), after=(2, 90.0, 0.0), statuses=(1, 1, 2)) as rsge:
            self._import(bill)
            with self.assertRaisesRegex(UserError, 'Reimport Lines'):
                bill.action_rs_buyer_accept()
            self.assertNotIn('acsept_invoice_status', rsge.calls)
            self.assertEqual(bill.state, 'draft')

            bill.action_rs_buyer_reimport_lines()
            bill.action_rs_buyer_accept()
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '2'))
        self.assertEqual(bill.amount_untaxed, 90)

    def test_vat_added_on_the_same_base_is_refused(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0), after=(2, 118.0, 18.0)):
            self._import(bill)
            with self.assertRaisesRegex(UserError, 'Reimport Lines'):
                bill.action_rs_buyer_accept()

    def test_accountants_edits_never_refuse(self):
        bill = self._bill()
        with self._rsge(before=(1.234, 3640.3, 555.3)):
            self._import(bill)
            bill.invoice_line_ids.tax_ids = self.purchase_vat_18_no_credit
            bill.invoice_line_ids = [Command.create({'name': 'Freight', 'quantity': 1, 'price_unit': 10})]
            bill.action_rs_buyer_accept()
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '2'))
        self.assertIn(self.purchase_vat_18_no_credit, bill.invoice_line_ids.tax_ids)

    def test_login_is_checked_once_per_transaction(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0)) as rsge:
            bill._rs_get_service(check_auth=True)
            bill._rs_get_service(check_auth=True)
        self.assertEqual(rsge.calls.count('chek'), 1)

    def test_vat_lines_take_the_company_default_purchase_tax(self):
        self.company.account_purchase_tax_id = self.purchase_vat_18_no_credit
        bill = self._bill()
        with self._rsge(before=(2, 118.0, 18.0)):
            self._import(bill)
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.purchase_vat_18_no_credit)
        self.assertEqual(bill.invoice_line_ids.price_unit, 50)

    def test_vat_lines_stay_untaxed_without_a_standard_default_purchase_tax(self):
        self.company.account_purchase_tax_id = self.env['account.tax'].create({
            'name': 'Reverse charge 18%', 'amount': 18, 'amount_type': 'percent',
            'type_tax_use': 'purchase', 'company_id': self.company.id,
        })
        bill = self._bill()
        with self._rsge(before=(2, 118.0, 18.0)):
            self._import(bill)
        self.assertFalse(bill.invoice_line_ids.tax_ids)
        self.assertEqual(bill.invoice_line_ids.price_unit, 59)

    def test_bill_not_built_from_rsge_lines_is_not_compared(self):
        bill = self._bill([(1, 70)])
        with self._rsge(before=(2, 90.0, 0.0)):
            bill.action_rs_buyer_accept()
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '2'))

    def test_accept_cut_off_after_rsge_accepted_leaves_a_postable_draft(self):
        bill = self._bill([(1, 70)])
        with self._rsge(before=(2, 100.0, 0.0), statuses=(1, 2)):
            with self._rsge_failing('buyer_accept_invoice', ReadTimeout), self.assertRaises(ReadTimeout):
                bill.action_rs_buyer_accept()
            self.assertEqual((bill.state, bill.rs_einv_status), ('draft', '1'))
            bill.action_rs_refresh_status()
            self.assertEqual(bill.rs_einv_status, '2')
            bill.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_accept_again_after_a_cut_off_posts_without_a_second_accept(self):
        bill = self._bill([(1, 70)])
        with self._rsge(before=(2, 100.0, 0.0), statuses=(1, 2)) as rsge:
            with self._rsge_failing('buyer_accept_invoice', ReadTimeout), self.assertRaises(ReadTimeout):
                bill.action_rs_buyer_accept()
            bill.action_rs_buyer_accept()
        self.assertEqual((bill.state, bill.rs_einv_status), ('posted', '2'))
        self.assertNotIn('acsept_invoice_status', rsge.calls)

    def test_confirm_button_shows_once_rsge_confirmed(self):
        arch = self.env['account.move'].get_views([(False, 'form')])['views']['form']['arch']
        invisible = etree.fromstring(arch).xpath("//header/button[@name='action_post'][@string='Confirm']")[0].get('invisible')
        bill = self._bill([(1, 70)])
        fields_in_use = ['hide_post_button', 'move_type', 'display_inactive_currency_warning', 'rs_einv_id', 'rs_einv_status', 'rs_einv_replaces_id',
            'rs_einv_replacement_mode']
        hidden = {}
        for status in ('1', '2', '8'):
            bill.rs_einv_status = status
            hidden[status] = safe_eval(invisible, bill.read(fields_in_use)[0])
        self.assertEqual(hidden, {'1': True, '2': False, '8': False})

    def test_post_is_refused_while_the_bill_is_pending_on_rsge(self):
        bill = self._bill([(1, 70)])
        with self.assertRaisesRegex(UserError, 'still pending on rs.ge'):
            bill.action_post()

    def test_post_refuses_lines_the_supplier_changed_after_import(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0), after=(2, 90.0, 0.0)):
            self._import(bill)
            bill.rs_einv_status = '2'
            bill._rs_refresh_pulled_lines(bill._rs_get_service())
            with self.assertRaisesRegex(UserError, 'Reimport Lines'):
                bill.action_post()
            bill.action_rs_buyer_reimport_lines()
            bill.action_post()
        self.assertEqual((bill.state, bill.amount_untaxed), ('posted', 90))

    def test_reimport_warns_when_vat_lines_stay_untaxed(self):
        bill = self._bill()
        with self._rsge(before=(2, 118.0, 18.0)):
            self._import(bill)
            self.company.account_purchase_tax_id = self.env['account.tax'].create({
                'name': 'Reverse charge 18%', 'amount': 18, 'amount_type': 'percent',
                'type_tax_use': 'purchase', 'company_id': self.company.id,
            })
            bill.action_rs_buyer_reimport_lines()
        warning = bill.rs_einv_log_ids.filtered(lambda log: log.level == 'warning' and 'No standard-rate' in log.name)
        self.assertTrue(warning)

    def test_empty_rsge_line_reply_keeps_the_snapshots(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0), statuses=(1, 1)):
            self._import(bill)
            snapshots = bill.rs_einv_pulled_line_ids
            with patch.object(type(self.env['rs.soap.service']), 'get_invoice_desc', return_value=[]):
                bill.action_rs_refresh_status()
                self.assertEqual(bill.rs_einv_pulled_line_ids, snapshots)
                with self.assertRaisesRegex(UserError, 'returned no lines'):
                    bill.action_rs_buyer_reimport_lines()

    def test_reimport_keeps_a_line_the_accountant_typed(self):
        bill = self._bill()
        with self._rsge(before=(2, 100.0, 0.0)):
            self._import(bill)
            bill.invoice_line_ids = [Command.create({'name': 'Freight', 'quantity': 1, 'price_unit': 10})]
            bill.action_rs_buyer_reimport_lines()
        self.assertEqual(sorted(bill.invoice_line_ids.mapped('name')), ['Cement', 'Freight'])

    def test_reimport_removes_extra_lines_of_a_bill_not_built_from_rsge_lines(self):
        bill = self._bill([(1, 70)])
        bill.invoice_line_ids = [Command.create({'name': 'Freight', 'quantity': 1, 'price_unit': 10})]
        with self._rsge(before=(2, 100.0, 0.0)):
            bill.action_rs_buyer_reimport_lines()
        self.assertEqual(bill.invoice_line_ids.mapped('name'), ['Cement'])
