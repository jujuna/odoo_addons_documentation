"""The rs.ge VAT class and amount of a line come from the Tax Category Code of its taxes."""

from datetime import date

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RsEinvoiceCommon


@tagged('post_install', '-at_install')
class TestVatClass(RsEinvoiceCommon):

    def _tax(self, name, code=False, **vals):
        return self.env['account.tax'].create({
            'name': name, 'amount': 0, 'amount_type': 'percent', 'type_tax_use': 'sale',
            'company_id': self.company.id, 'ubl_cii_tax_category_code': code, **vals,
        })

    def _line(self, taxes, price_unit=50, quantity=2, name='Service'):
        return Command.create({
            'name': name, 'quantity': quantity, 'price_unit': price_unit,
            'tax_ids': [Command.set(taxes.ids)],
        })

    def _payloads(self, *lines):
        move = self._invoice(invoice_line_ids=list(lines))
        return move, move._rs_lines_to_payload(move.invoice_line_ids)

    def test_standard_line_vat_is_price_total_minus_subtotal(self):
        move, payloads = self._payloads(self._line(self.tax_18))
        line = move.invoice_line_ids
        self.assertEqual(payloads[0]['vat_amount'], 18.0)
        self.assertEqual(payloads[0]['vat_amount'], line.price_total - line.price_subtotal)

    def test_zero_rated_and_exempt_codes(self):
        for code, expected in (('E', -1), ('Z', 0), ('G', 0)):
            with self.subTest(code=code):
                tax = self._tax('Zero %s' % code, code)
                _move, payloads = self._payloads(self._line(tax))
                self.assertEqual(payloads[0]['vat_amount'], expected)

    def test_uncoded_fixed_tax_alone_is_not_vat(self):
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        _move, payloads = self._payloads(self._line(city_tax, price_unit=0, quantity=1))
        self.assertEqual(payloads[0]['vat_amount'], -1)
        self.assertAlmostEqual(payloads[0]['full_amount'], 2.10)

    def test_uncoded_fixed_tax_is_left_out_of_the_vat(self):
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        move, payloads = self._payloads(self._line(self.tax_18 | city_tax))
        self.assertEqual(payloads[0]['vat_amount'], 18.0)
        self.assertAlmostEqual(payloads[0]['full_amount'], move.invoice_line_ids.price_total)

    def test_price_included_standard_tax_with_uncoded_fixed_tax(self):
        vat_included = self._tax('VAT 18% included', 'S', amount=18, price_include_override='tax_included')
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        move, payloads = self._payloads(self._line(vat_included | city_tax, price_unit=118, quantity=1))
        line = move.invoice_line_ids
        taxes = line.tax_ids.compute_all(line.price_unit, line.currency_id, line.quantity)['taxes']
        standard_vat = sum(t['amount'] for t in taxes if t['id'] == vat_included.id)
        self.assertAlmostEqual(payloads[0]['vat_amount'], standard_vat, places=2)
        self.assertNotAlmostEqual(payloads[0]['vat_amount'], line.price_total - line.price_subtotal, places=2)

    def test_foreign_currency_vat_is_converted_to_gel(self):
        usd = self.env.ref('base.USD')
        usd.active = True
        usd.rate_ids.unlink()
        self.env['res.currency.rate'].create({
            'currency_id': usd.id, 'company_id': self.company.id, 'name': date(2026, 9, 1), 'rate': 0.4,
        })
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        move = self._invoice(
            currency_id=usd.id, invoice_date=date(2026, 9, 20),
            invoice_line_ids=[self._line(self.tax_18 | city_tax)],
        )
        payload = move._rs_lines_to_payload(move.invoice_line_ids)[0]
        vat_lines = move.line_ids.filtered(lambda l: l.tax_line_id == self.tax_18)
        self.assertAlmostEqual(payload['vat_amount'], abs(sum(vat_lines.mapped('balance'))), places=2)
        self.assertNotAlmostEqual(payload['vat_amount'], 18.0, places=2)

    def test_downpayment_offset_reduces_standard_lines_only(self):
        if 'is_downpayment' not in self.env['account.move.line']._fields:
            self.skipTest("is_downpayment comes from the sale module")
        exempt = self._tax('Exempt', 'E')
        move = self._invoice(rs_einv_advance_settlement_mode='net', invoice_line_ids=[
            self._line(self.tax_18, price_unit=100, quantity=1, name='Taxed'),
            self._line(exempt, price_unit=50, quantity=1, name='Exempt'),
            Command.create({
                'name': 'Down payment', 'quantity': 1, 'price_unit': -50,
                'tax_ids': [Command.set(self.tax_18.ids)], 'is_downpayment': True,
            }),
        ])
        taxed, exempt_line, offset = move.invoice_line_ids
        payloads = {p['goods']: p for p in move._rs_lines_to_payload(move.invoice_line_ids)}
        self.assertEqual(set(payloads), {'Taxed', 'Exempt'})
        self.assertEqual(payloads['Exempt']['vat_amount'], -1)
        self.assertAlmostEqual(payloads['Exempt']['full_amount'], exempt_line.price_total)
        self.assertAlmostEqual(payloads['Taxed']['full_amount'], taxed.price_total + offset.price_total)
        offset_vat = move._rs_line_vat_class(offset)[1]
        self.assertAlmostEqual(payloads['Taxed']['vat_amount'], 18.0 - offset_vat)

    def test_validate_needs_a_sale_tax_with_code_s(self):
        invoice = self._invoice(invoice_date=date(2026, 9, 20))
        invoice.action_post()
        invoice._rs_validate()
        self.env['account.tax'].search([
            ('company_id', '=', self.company.id), ('type_tax_use', '=', 'sale'),
        ]).ubl_cii_tax_category_code = False
        with self.assertRaisesRegex(UserError, 'Tax Category Code S'):
            invoice._rs_validate()

    def test_validate_refuses_a_percent_tax_rs_ge_does_not_know(self):
        for code in (False, 'AE'):
            with self.subTest(code=code):
                tax = self._tax('Hand-made VAT %s' % code, code, amount=18)
                invoice = self._invoice(invoice_date=date(2026, 9, 20), invoice_line_ids=[self._line(tax)])
                invoice.action_post()
                with self.assertRaisesRegex(UserError, 'Hand-made VAT'):
                    invoice._rs_validate()

    def test_validate_allows_an_uncoded_fixed_tax(self):
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        invoice = self._invoice(invoice_date=date(2026, 9, 20), invoice_line_ids=[self._line(self.tax_18 | city_tax)])
        invoice.action_post()
        invoice._rs_validate()

    def _mixed_invoice(self):
        exempt = self._tax('Exempt', 'E')
        zero = self._tax('Zero', 'Z')
        city_tax = self._tax('City Tax', amount_type='fixed', amount=2.10)
        return self._invoice(invoice_line_ids=[
            self._line(self.tax_18, name='Taxed'),
            self._line(exempt, name='Exempt'),
            self._line(zero, name='Zero'),
            self._line(city_tax, price_unit=0, quantity=1, name='City'),
            Command.create({'display_type': 'line_section', 'name': 'Section'}),
        ])

    def test_seller_vat_totals_count_standard_lines_only(self):
        move = self._mixed_invoice()
        taxed, exempt, zero, city = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        self.assertEqual(move._rs_line_vat_abs_gel(taxed), 18.0)
        self.assertEqual(move._rs_line_vat_abs_gel(exempt), 0.0)
        self.assertEqual(move._rs_line_vat_abs_gel(zero), 0.0)
        self.assertEqual(move._rs_line_vat_abs_gel(city), 0.0)
        self.assertEqual(move._rs_move_vat_abs_gel(move), 18.0)

    def test_preview_fields(self):
        move = self._mixed_invoice()
        lines = move.invoice_line_ids
        self.assertEqual(
            [(l.rs_einv_vat_class, l.rs_einv_vat_amount) for l in lines if l.display_type == 'product'],
            [('taxable', 18.0), ('untaxed', 0.0), ('zero', 0.0), ('untaxed', 0.0)],
        )
        section = lines.filtered(lambda l: l.display_type == 'line_section')
        self.assertFalse(section.rs_einv_vat_class)
        self.assertEqual(section.rs_einv_vat_amount, 0.0)
