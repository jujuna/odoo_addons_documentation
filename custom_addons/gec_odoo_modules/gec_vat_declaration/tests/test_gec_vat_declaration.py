import io
from datetime import date

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.gec_vat_declaration.models.gec_vat_declaration import (
    COLUMN4_SOURCE, DEDUCTION_DECREASE_CELL, FIXED_ASSET_SOURCE, MARGIN_ROWS, NET_VAT_SOURCE, ODOO_SOURCE)
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, HttpCase, tagged
from odoo.tools import file_open, format_date
from odoo.tools.pdf import PdfWriter

CUSTOMS_FONT = 'gec_vat_declaration/tests/NotoSansGeorgian-Regular.ttf'


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestGecVatDeclaration(AccountTestInvoicingCommon):
    """The catalog, Generate from the l10n_ge VAT report, and the recompute after typing a cell."""

    @classmethod
    @AccountTestInvoicingCommon.setup_country('ge')
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env['account.chart.template'].ref
        cls.tax_sale = ref('ge_vat_sale_18')
        cls.tax_purchase = ref('ge_vat_purchase_18')
        georgia = cls.env.ref('base.ge')
        cls.customer = cls.env['res.partner'].create(
            {'name': 'GE customer', 'country_id': georgia.id, 'vat': '204567890'})
        cls.vendor = cls.env['res.partner'].create(
            {'name': 'GE vendor', 'country_id': georgia.id, 'vat': '205678901'})
        cls.revenue = cls.company_data['default_account_revenue']
        cls.expense = cls.company_data['default_account_expense']
        cls._invoice('out_invoice', cls.customer, '2026-09-10', 5420.0, cls.tax_sale, cls.revenue, post=True)
        cls._invoice('in_invoice', cls.vendor, '2026-09-12', 2777.78, cls.tax_purchase, cls.expense, post=True)
        cls.env.company.loss_account_id = cls.expense.copy()
        cls.env.company.gain_account_id = cls.revenue.copy()
        with file_open(CUSTOMS_FONT, 'rb') as font:
            pdfmetrics.registerFont(TTFont('NotoGeorgian', font))
        face = pdfmetrics.getFont('NotoGeorgian').face
        for char in '0123456789,./:–':
            face.charToGlyph[ord(char)] = face.charToGlyph[ord('ა')]

    @classmethod
    def _invoice(cls, move_type, partner, date, price, tax, account, post=False):
        return cls._create_invoice(
            move_type=move_type, partner_id=partner, invoice_date=date,
            invoice_line_ids=[cls._prepare_invoice_line(
                price_unit=price, tax_ids=tax, account_id=account, name='Line')],
            post=post,
        )

    def _generated(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-09-01'})
        declaration.action_generate()
        return declaration

    def _generated_august(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-08-01'})
        declaration.action_generate()
        return declaration

    def _margin_asset(self, scheme, value, name=None):
        asset = self.env['account.asset'].create({
            'name': name or 'Margin %s' % scheme,
            'original_value': value,
            'acquisition_date': '2026-07-01',
            'account_asset_id': self.company_data['default_account_assets'].id,
            'model_id': self.env.ref('account_asset.asset_no_depreciation').id,
            'gec_margin_scheme': scheme,
        })
        asset.validate()
        return asset

    def _sale_invoice(self, prices, date='2026-08-10', tax=None):
        return self._create_invoice(
            partner_id=self.partner_a, invoice_date=date, post=True,
            invoice_line_ids=[
                self._prepare_invoice_line(
                    price_unit=price, name='Item %s' % index, tax_ids=tax or self.env['account.tax'])
                for index, price in enumerate(prices)])

    def _sell(self, asset, lines, date='2026-08-10'):
        self.env['asset.modify'].create({
            'asset_variant_id': asset.main_variant_id.id,
            'modify_action': 'sell',
            'invoice_line_ids': lines,
            'date': date,
        }).sell_dispose()

    def _reverse(self, move):
        self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=move.ids).create(
            {'date': '2026-08-20', 'reason': 'test', 'journal_id': move.journal_id.id}).refund_moves()
        return move.reversal_move_ids

    def _customs_pdf(self, number='A147622', issued='16/10/2026', amount='2261.40'):
        """A customs declaration page with the sample's label and value positions; a missing value is not drawn."""
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        for x, y, font, text in [
            (400, 806, 'NotoGeorgian', 'გაფორმების საგადასახადო ორგანო'), (286, 788, 'NotoGeorgian', 'იმ'),
            (315, 788, 'Helvetica', '4'), (400, 794, 'Helvetica', '11111'),
            (329, 210, 'NotoGeorgian', 'შეფასების'), (386, 209, 'Helvetica', number),
            (485, 210, 'NotoGeorgian', 'თარ.'), (513, 209, 'Helvetica', issued),
            (329, 153, 'NotoGeorgian', 'გადახდილია სულ'), (453, 152, 'Helvetica', amount),
            (485, 153, 'NotoGeorgian', 'ლარი'),
        ]:
            if text:
                pdf.setFont(font, 7)
                pdf.drawString(x, y, text)
        pdf.save()
        return buffer.getvalue()

    def _form4_pdf(self, number='20010/2395611', issued='01.08.2026  00:21:22', vat='101001000   374.04', dash='-'):
        """A Form 4 page with the sample's label and value positions and its other digits; a missing value is not
        drawn. The font has no digits or en dash: they borrow a Georgian glyph, so that the text comes out as typed."""
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.setFont('NotoGeorgian', 7)
        for x, y, text in [
            (255, 696, '6. დეკლარაციის რეგისტრაციის'), (295, 675, number),
            (17, 461, '10. რეგისტრაციის თარიღი'), (102, 437, issued),
            (258, 424, 'დღგ                  %sსახაზ. კოდი     %s' % (dash, vat) if vat else ''),
            (258, 438, 'მ.შ იმპორტის გადასახადი  - სახაზ. კოდი     101001000            0'),
            (473, 559, 'დღგ'), (468, 480, '374.04'),
        ]:
            if text:
                pdf.drawString(x, y, text)
        pdf.save()
        return buffer.getvalue()

    def _blank_pdf(self):
        blank = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(blank)
        return blank.getvalue()

    def _customs_attachment(self, **values):
        return self.env['ir.attachment'].create({'name': 'customs.pdf', 'raw': self._customs_pdf(**values)})

    def _form4_attachment(self, **values):
        return self.env['ir.attachment'].create({'name': 'form4.pdf', 'raw': self._form4_pdf(**values)})

    def _warning(self, declaration, fragment):
        lines = (declaration.generation_warnings or '').splitlines()
        return next((line for line in lines if fragment in line), '')

    def _values(self, declaration):
        return {line.code: line.value for line in declaration.line_ids}

    def _line(self, declaration, code):
        return declaration.line_ids.filtered(lambda cell: cell.code == code)

    def _type(self, declaration, tab, values):
        declaration.write({tab: [
            Command.update(self._line(declaration, code).id, {'value': value})
            for code, value in values.items()]})

    def _assert_values(self, declaration, expected):
        values = self._values(declaration)
        for code, value in expected.items():
            self.assertAlmostEqual(values[code], value, places=2, msg=code)

    def test_catalog_counts(self):
        counts = {
            tab: self.env['gec.vat.cell'].search_count([('tab', '=', tab)])
            for tab in ('1', '2', '3', '16', '17')}
        self.assertEqual(counts, {'1': 32, '2': 7, '3': 33, '16': 24, '17': 13})

    def test_catalog_grid_layout(self):
        cells = self.env['gec.vat.cell'].search([])
        positions = [(cell.tab, cell.line, cell.slot) for cell in cells]
        self.assertEqual(len(positions), len(set(positions)))
        lines = {tab: {cell.line for cell in cells if cell.tab == tab} for tab in ('1', '2', '3', '16', '17')}
        self.assertEqual({tab: len(keys) for tab, keys in lines.items()}, {'1': 22, '2': 4, '3': 11, '16': 20, '17': 5})
        slots = {
            tab: {slot: len(cells.filtered(lambda cell: cell.tab == tab and cell.slot == slot)) for slot in (1, 2, 3)}
            for tab in lines}
        self.assertEqual(slots, {
            '1': {1: 20, 2: 12, 3: 0},
            '2': {1: 3, 2: 4, 3: 0},
            '3': {1: 11, 2: 11, 3: 11},
            '16': {1: 10, 2: 8, 3: 6},
            '17': {1: 4, 2: 4, 3: 5},
        })

    def test_generate_month(self):
        declaration = self._generated()
        self._assert_values(declaration, {
            '355_1': 5420.0, '355_1_5': 975.60, '358_1': 975.60, '358_2': 5420.0,
            '353_14': 500.0, '353_13': 500.0, '358_11': 500.0, '358_17': 475.0, '358_18': 0.0,
        })

    def test_typed_fixed_asset_vat_moves_out_of_column_4(self):
        declaration = self._generated()
        self._type(declaration, 'tab3_line_ids', {'353_15': 100.0})
        self._assert_values(declaration, {'353_14': 400.0, '353_15': 100.0, '353_13': 500.0, '358_11': 500.0})

    def test_typed_correction_changes_result(self):
        declaration = self._generated()
        self._type(declaration, 'tab16_line_ids', {'358_7': 54.0})
        self._assert_values(declaration, {'358_16': 554.0, '358_17': 421.0, '358_18': 0.0})
        self._type(declaration, 'tab16_line_ids', {'358_7': 1000.0})
        self._assert_values(declaration, {'358_16': 1500.0, '358_17': 0.0, '358_18': 524.0})

    def test_draft_entries_and_other_companies_not_counted(self):
        self._invoice('out_invoice', self.customer, '2026-09-15', 1000.0, self.tax_sale, self.revenue)
        other = self.setup_other_company()
        company = other['company']
        tax = self.env['account.chart.template'].with_company(company).ref('ge_vat_sale_18')
        self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'invoice_date': '2026-09-16',
            'invoice_line_ids': [Command.create({
                'name': 'Other company', 'price_unit': 1000.0, 'tax_ids': [Command.set(tax.ids)],
                'account_id': other['default_account_revenue'].id})],
        }).action_post()
        declaration = self._generated()
        self._assert_values(declaration, {'355_1': 5420.0})

    def test_annex_b1_vat_counts_only_standard_rate_taxes(self):
        city_tax = self.env['account.tax'].create({
            'name': 'City Tax', 'type_tax_use': 'sale', 'amount_type': 'fixed', 'amount': 2.10})
        invoice = self._invoice(
            'out_invoice', self.customer, '2026-09-20', 100.0, self.tax_sale | city_tax, self.revenue, post=True)
        invoice.write({'rs_einv_series': 'AB', 'rs_einv_number': '12345', 'rs_einv_status': '2'})
        declaration = self._generated()
        row = declaration.invoice_line_ids.filtered(lambda line: line.move_id == invoice)
        self.assertEqual(row.amount, 18.0)
        self.assertEqual(row.reduce_amount, 0.0)

    def test_annex_b2_vat_counts_only_standard_rate_taxes(self):
        city_tax = self.env['account.tax'].create({
            'name': 'City Tax', 'type_tax_use': 'purchase', 'amount_type': 'fixed', 'amount': 2.10})
        bill = self._invoice(
            'in_invoice', self.vendor, '2026-09-20', 100.0, self.tax_purchase | city_tax, self.expense, post=True)
        bill.write({'rs_einv_series': 'AB', 'rs_einv_number': '54321', 'rs_einv_status': '2'})
        declaration = self._generated()
        row = declaration.purchase_line_ids.filtered(lambda line: line.move_id == bill)
        self.assertEqual(row.amount, 18.0)

    def test_typed_proposed_cell_survives_generate(self):
        declaration = self._generated()
        self._type(declaration, 'tab1_line_ids', {'355_1': 5000.0})
        self._invoice('out_invoice', self.customer, '2026-09-20', 580.0, self.tax_sale, self.revenue, post=True)
        declaration.action_generate()
        line = self._line(declaration, '355_1')
        self.assertAlmostEqual(line.value, 5000.0)
        self.assertAlmostEqual(line.proposed_value, 6000.0)

    def test_month_lock_and_filed_lock(self):
        declaration = self._generated()
        with self.assertRaises(UserError):
            declaration.write({'date_from': '2026-08-01'})
        declaration.action_mark_filed()
        with self.assertRaises(UserError):
            self._line(declaration, '355_1').write({'value': 1.0})

    def test_current_month_cannot_be_marked_filed(self):
        month = fields.Date.context_today(self.env.company).replace(day=1)
        declaration = self.env['gec.vat.declaration'].create({'date_from': month})
        lock_date = self.env.company.tax_lock_date
        with self.assertRaises(UserError):
            declaration.action_mark_filed()
        self.assertEqual(declaration.state, 'draft')
        self.assertEqual(self.env.company.tax_lock_date, lock_date)

    def test_typed_row_cannot_move_into_a_filed_declaration(self):
        draft = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        row = self.env['gec.vat.ref.line'].create({
            'declaration_id': draft.id,
            'grid': 'b4',
            'ref_number': 'D-1',
            'amount': 10.0,
        })
        filed = self.env['gec.vat.declaration'].create({'date_from': '2026-08-01'})
        filed.action_mark_filed()
        with self.assertRaises(UserError):
            row.write({'declaration_id': filed.id})
        self.assertEqual(row.declaration_id, draft)

    def test_mark_filed_refused_while_an_earlier_month_is_not_filed(self):
        august = self._generated_august()
        september = self._generated()
        with self.assertRaises(UserError) as error:
            september.action_mark_filed()
        self.assertIn(august.name, str(error.exception))
        self.assertEqual(september.state, 'draft')
        august.action_mark_filed()
        adjusted = self._generated_august()
        self.assertEqual(adjusted.decl_type, 'adjusted')
        september.action_mark_filed()
        self.assertEqual(september.state, 'filed')

    def test_copy_of_a_filed_declaration_is_an_adjusted_draft_with_its_typed_values(self):
        original = self._generated_august()
        self._type(original, 'tab1_line_ids', {'355_1': 5000.0})
        original.write({
            'invoice_line_ids': [Command.create({'part': 'sale', 'amount': 18.0})],
            'customs_line_ids': [Command.create({'assessment_number': 'A1', 'amount': 5.0})],
            'b4_line_ids': [Command.create({'grid': 'b4', 'amount': 10.0})],
            'b5_line_ids': [Command.create({'grid': 'b5', 'amount': 20.0})],
            'b8_line_ids': [Command.create({'grid': 'b8', 'amount': 30.0})],
            'b9_line_ids': [Command.create({'grid': 'b9', 'amount': 40.0})],
        })
        original.action_mark_filed()
        copy = original.copy()
        self.assertEqual((copy.state, copy.decl_type), ('draft', 'adjusted'))
        self.assertAlmostEqual(self._line(copy, '355_1').value, 5000.0)
        self.assertEqual(len(copy.line_ids), len(original.line_ids))
        for field in ('invoice_line_ids', 'customs_line_ids', 'b4_line_ids', 'b5_line_ids', 'b8_line_ids', 'b9_line_ids'):
            self.assertEqual(len(copy[field]), 1, field)

    def test_copy_of_a_declaration_without_a_filed_month_stays_primary(self):
        copy = self._generated().copy()
        self.assertEqual((copy.state, copy.decl_type), ('draft', 'primary'))

    def test_december_only_cells(self):
        december = self.env['gec.vat.declaration'].create({'date_from': '2026-12-01'})
        november = self.env['gec.vat.declaration'].create({'date_from': '2026-11-01'})
        self.assertFalse(self._line(december, '353_64').locked)
        self.assertTrue(self._line(november, '353_64').locked)
        self._type(december, 'tab3_line_ids', {'353_64': 36.0})
        self._assert_values(december, {'353_63': 36.0, '358_11': 36.0})

    def test_formulas_without_invoices(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-09-01'})
        self._type(declaration, 'tab2_line_ids', {'356_1': 1000.0})
        self._assert_values(declaration, {'356_15': 180.0, '356_4': 180.0, '358_8': 180.0})
        self._type(declaration, 'tab17_line_ids', {'359_1': 1000.0, '359_1_4': 1180.0})
        self._assert_values(declaration, {'359_1_5': 27.46, '358_17': 207.0})
        self._type(declaration, 'tab17_line_ids', {'359_1_4': 500.0})
        self._assert_values(declaration, {'359_1_5': 0.0, '358_17': 180.0})

    def test_constants_match_core_report_and_catalog(self):
        expressions = self.env.ref('l10n_ge.tax_report_ge').line_ids.expression_ids
        existing = {(expression.report_line_id.code, expression.label) for expression in expressions}
        pairs = set(ODOO_SOURCE.values()) | {NET_VAT_SOURCE}
        self.assertFalse(pairs - existing)
        proposal_codes = set(ODOO_SOURCE) - set(self.env['gec.vat.cell'].search([('computed', '=', True)]).mapped('code'))
        proposed = set(self.env['gec.vat.cell'].search([('proposed', '=', True)]).mapped('code'))
        margin_codes = {code for row in MARGIN_ROWS for code in ('359_%s' % row, '359_%s_4' % row)}
        self.assertEqual(proposed, proposal_codes | set(COLUMN4_SOURCE) | set(FIXED_ASSET_SOURCE) | margin_codes | {DEDUCTION_DECREASE_CELL})

    def test_credit_notes_above_bills_are_proposed_in_row_12(self):
        bill = self._invoice('in_invoice', self.vendor, '2026-06-10', 500.0, self.tax_purchase, self.expense, post=True)
        bill.write({'rs_einv_series': 'AB', 'rs_einv_number': '54321', 'rs_einv_status': '2'})
        self._invoice('in_refund', self.vendor, '2026-06-12', 1000.0, self.tax_purchase, self.expense, post=True)
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-06-01'})
        declaration.action_generate()
        self._assert_values(declaration, {'353_14': -90.0, '358_11': 0.0, '358_12': 90.0, '358_15': 90.0})
        self.assertAlmostEqual(self._line(declaration, '358_12').proposed_value, 90.0)
        self.assertTrue(self._warning(declaration, 'A III row 1 column 4 is negative'))
        self._type(declaration, 'tab16_line_ids', {'358_12': 30.0})
        declaration.action_generate()
        self.assertAlmostEqual(self._line(declaration, '358_12').value, 30.0)
        self.assertAlmostEqual(self._line(declaration, '358_12').proposed_value, 90.0)

    def test_margin_assets_per_category(self):
        assets = [
            self._margin_asset(scheme, value)
            for scheme, value in (('second_hand', 1000.0), ('art', 500.0), ('collectible', 300.0), ('antique', 200.0))]
        invoice = self._sale_invoice([1180.0, 618.0, 354.0, 500.0])
        for asset, line in zip(assets, invoice.invoice_line_ids):
            self._sell(asset, line)
            self.assertEqual(line.gec_sold_asset_id, asset)
        declaration = self._generated_august()
        self._assert_values(declaration, {
            '359_1': 1000.0, '359_1_4': 1180.0, '359_1_5': 27.46,
            '359_2': 500.0, '359_2_4': 618.0, '359_2_5': 18.0,
            '359_3': 300.0, '359_3_4': 354.0, '359_3_5': 8.24,
            '359_4': 200.0, '359_4_4': 500.0, '359_4_5': 45.76,
            '359_5': 99.46, '355_1_1_5': 99.46,
        })
        for row in MARGIN_ROWS:
            for code in ('359_%s' % row, '359_%s_4' % row):
                line = self._line(declaration, code)
                self.assertAlmostEqual(line.proposed_value, line.value, places=2, msg=code)
        self.assertFalse(self._warning(declaration, 'sold with a tax'))
        self.assertFalse(self._warning(declaration, 'no longer closed'))

    def test_margin_resell_moves_link(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice_x = self._sale_invoice([1180.0])
        self._sell(asset, invoice_x.invoice_line_ids)
        asset.set_to_running()
        invoice_y = self._sale_invoice([1300.0], date='2026-08-15')
        self._sell(asset, invoice_y.invoice_line_ids, date='2026-08-15')
        self.assertFalse(invoice_x.invoice_line_ids.gec_sold_asset_id)
        self.assertEqual(invoice_y.invoice_line_ids.gec_sold_asset_id, asset)
        declaration = self._generated_august()
        self._assert_values(declaration, {'359_1': 1000.0, '359_1_4': 1300.0})

    def test_margin_second_asset_sold_on_a_line_after_the_first_is_set_to_running(self):
        asset_a, asset_b = self._margin_asset('second_hand', 1000.0, 'Asset A'), self._margin_asset('second_hand', 800.0, 'Asset B')
        line = self._sale_invoice([1180.0]).invoice_line_ids
        self._sell(asset_a, line)
        asset_a.set_to_running()
        self._sell(asset_b, line)
        self.assertEqual(line.gec_sold_asset_id, asset_b)

    def test_margin_second_asset_refused_on_a_line_while_the_first_is_sold(self):
        asset_a, asset_b = self._margin_asset('second_hand', 1000.0, 'Asset A'), self._margin_asset('second_hand', 800.0, 'Asset B')
        line = self._sale_invoice([1180.0]).invoice_line_ids
        self._sell(asset_a, line)
        with self.assertRaisesRegex(UserError, 'already sold'):
            self._sell(asset_b, line)
        self.assertEqual(line.gec_sold_asset_id, asset_a)

    def test_margin_taxed_line_warning(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1000.0], tax=self.tax_sale)
        self._sell(asset, invoice.invoice_line_ids)
        declaration = self._generated_august()
        self._assert_values(declaration, {'359_1_4': 1000.0})
        self.assertIn(invoice.name, self._warning(declaration, 'sold with a tax'))

    def test_margin_reopened_asset_warning(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1180.0])
        self._sell(asset, invoice.invoice_line_ids)
        asset.set_to_running()
        declaration = self._generated_august()
        self._assert_values(declaration, {'359_1_4': 1180.0})
        self.assertIn(asset.display_name, self._warning(declaration, 'no longer closed'))

    def test_margin_credit_note_warning(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1180.0])
        self._sell(asset, invoice.invoice_line_ids)
        credit = self._reverse(invoice)
        credit.action_post()
        declaration = self._generated_august()
        self.assertIn(credit.name, self._warning(declaration, 'credit notes'))

    def test_margin_resale_after_credit_note(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice_x = self._sale_invoice([1180.0])
        self._sell(asset, invoice_x.invoice_line_ids)
        credit = self._reverse(invoice_x)
        credit.action_post()
        asset.set_to_running()
        invoice_y = self._sale_invoice([1250.0], date='2026-09-12')
        self._sell(asset, invoice_y.invoice_line_ids, date='2026-09-12')
        self.assertEqual(invoice_x.invoice_line_ids.gec_sold_asset_id, asset)
        self.assertEqual(invoice_y.invoice_line_ids.gec_sold_asset_id, asset)
        august = self._generated_august()
        self._assert_values(august, {'359_1': 1000.0, '359_1_4': 1180.0})
        self.assertIn(credit.name, self._warning(august, 'credit notes'))
        september = self._generated()
        self._assert_values(september, {'359_1': 1000.0, '359_1_4': 1250.0, '359_1_5': 38.14})
        self.assertFalse(self._warning(september, 'already counted'))

    def test_margin_typed_purchase_price_kept(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1180.0])
        self._sell(asset, invoice.invoice_line_ids)
        declaration = self._generated_august()
        self._type(declaration, 'tab17_line_ids', {'359_1': 900.0})
        declaration.action_generate()
        self._assert_values(declaration, {'359_1': 900.0, '359_1_4': 1180.0, '359_1_5': 42.71})

    def test_margin_sell_after_invoice_month(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1180.0])
        self._sell(asset, invoice.invoice_line_ids, date='2026-09-05')
        august = self._generated_august()
        self._assert_values(august, {'359_1': 1000.0, '359_1_4': 1180.0})
        warning = self._warning(self._generated(), 'on an invoice of another month')
        self.assertIn(asset.display_name, warning)
        self.assertIn('08/2026', warning)

    def test_customs_parser_reads_by_position(self):
        parse = self.env['gec.vat.declaration']._gec_parse_pdf
        self.assertEqual(parse(self._customs_pdf()), {
            'pdf_type': 'customs', 'assessment_number': 'A147622', 'customs_code': '11111',
            'assessment_date': date(2026, 10, 16), 'amount': 2261.4})
        self.assertFalse(parse(self._customs_pdf(amount=''))['amount'])
        self.assertFalse(parse(self._customs_pdf(number=''))['assessment_number'])
        self.assertFalse(parse(self._customs_pdf(amount='2261,40'))['amount'])
        self.assertEqual(parse(self._customs_pdf(amount='2,261.40'))['amount'], 2261.4)

    def test_form4_parser_reads_by_position(self):
        parse = self.env['gec.vat.declaration']._gec_parse_pdf
        self.assertEqual(parse(self._form4_pdf()), {
            'pdf_type': 'form4', 'assessment_number': '20010/2395611', 'customs_code': '101001000',
            'assessment_date': date(2026, 8, 1), 'amount': 374.04})
        self.assertEqual(parse(self._form4_pdf(vat='101001000   1,374.04'))['amount'], 1374.04)
        self.assertEqual(parse(self._form4_pdf(dash='–'))['amount'], 374.04)
        self.assertFalse(parse(self._form4_pdf(number=''))['assessment_number'])
        self.assertFalse(parse(self._form4_pdf(issued=''))['assessment_date'])
        no_vat = parse(self._form4_pdf(vat=''))
        self.assertEqual((no_vat['pdf_type'], no_vat['customs_code'], no_vat['amount']), ('form4', False, False))

    def test_pdf_type_detected_per_file(self):
        parse = self.env['gec.vat.declaration']._gec_parse_pdf
        self.assertEqual(parse(self._customs_pdf())['pdf_type'], 'customs')
        self.assertEqual(parse(self._form4_pdf())['pdf_type'], 'form4')
        self.assertEqual(parse(self._blank_pdf()), dict.fromkeys(
            ('pdf_type', 'assessment_number', 'customs_code', 'assessment_date', 'amount'), False))

    def test_customs_upload_reads_both_types(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-08-01'})
        attachments = self._customs_attachment(issued='16/08/2026') | self._form4_attachment()
        declaration.action_gec_customs_upload(attachments.ids)
        customs, form4 = declaration.customs_line_ids
        self.assertEqual((customs.pdf_type, customs.assessment_number), ('customs', 'A147622'))
        self.assertEqual(
            (form4.pdf_type, form4.assessment_number, form4.customs_code, form4.assessment_date, form4.amount),
            ('form4', '20010/2395611', '101001000', date(2026, 8, 1), 374.04))
        self.assertEqual(declaration.customs_line_ids.attachment_id, attachments)
        self.assertAlmostEqual(declaration.b3_amount, 2635.44)
        self.assertEqual(declaration._gec_customs_row_vals(attachments[1], {'pdf_type': 'form4'}), {
            'pdf_type': 'form4', 'declaration_id': declaration.id, 'attachment_id': attachments[1].id})

    def test_customs_upload_of_unrecognised_pdf_leaves_an_empty_row(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        attachment = self.env['ir.attachment'].create({'name': 'other.pdf', 'raw': self._blank_pdf()})
        declaration.action_gec_customs_upload(attachment.ids)
        self.assertFalse(declaration.customs_line_ids.pdf_type)
        self.assertFalse(declaration.customs_line_ids.assessment_number)
        self.assertTrue(self._warning(declaration, 'other.pdf: the number'))

    def test_typed_ref_rows_keep_their_grid(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        with Form(declaration) as form:
            with form.b4_line_ids.new() as line:
                line.ref_number = 'D-1'
                line.amount = 30.0
            with form.b5_line_ids.new() as line:
                line.ref_number = '20010/1'
                line.period = date(2026, 10, 1)
                line.amount = 12.5
        self.assertEqual(declaration.b4_line_ids.mapped('ref_number'), ['D-1'])
        self.assertEqual(declaration.b5_line_ids.mapped('ref_number'), ['20010/1'])
        self.assertEqual(declaration.b5_line_ids.period, date(2026, 10, 1))
        self.assertEqual((declaration.b4_amount, declaration.b5_amount), (30.0, 12.5))

    def test_b8_row_takes_the_month_of_the_declaration_with_its_number(self):
        earlier = self.env['gec.vat.declaration'].create({'date_from': '2026-08-01'})
        earlier.portal_number = 'P-8'
        declaration = self._generated()
        before = self._values(declaration)
        with Form(declaration) as form:
            with form.b8_line_ids.new() as line:
                line.ref_number = 'P-8'
                line.amount = 25.0
        declaration.action_generate()
        row = declaration.b8_line_ids
        self.assertEqual((row.grid, row.period, declaration.b8_amount), ('b8', date(2026, 8, 1), 25.0))
        self._assert_values(declaration, {code: before[code] for code in ('358_7', '358_10', '358_16')})

    def test_b8_period_follows_the_number_but_is_kept_when_typed(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        with Form(declaration) as form:
            with form.b8_line_ids.new() as line:
                line.ref_number = 'NOBODY-1'
                line.amount = 10.0
        row = declaration.b8_line_ids
        self.assertFalse(row.period)
        with Form(declaration) as form:
            with form.b8_line_ids.edit(0) as line:
                line.period = date(2026, 7, 1)
        self.assertEqual(row.period, date(2026, 7, 1))
        row.ref_number = 'NOBODY-2'
        self.assertFalse(row.period)

    def test_b9_row_also_looks_at_reverse_charge_calculations(self):
        self.env['gec.vat.rc.declaration'].create({'date_from': '2026-08-01', 'portal_number': 'RC-1'})
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        declaration.write({
            'b8_line_ids': [Command.create({'ref_number': 'RC-1', 'amount': 5.0})],
            'b9_line_ids': [Command.create({'ref_number': 'RC-1', 'amount': 5.0})]})
        self.assertFalse(declaration.b8_line_ids.period)
        self.assertEqual(declaration.b9_line_ids.period, date(2026, 8, 1))

    def test_b8_row_ignores_the_declaration_of_another_company(self):
        other = self.setup_other_company()['company']
        self.env['gec.vat.declaration'].create({'date_from': '2026-08-01', 'company_id': other.id, 'portal_number': 'P-9'})
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        declaration.write({'b8_line_ids': [Command.create({'ref_number': 'P-9', 'amount': 5.0})]})
        self.assertFalse(declaration.b8_line_ids.period)

    def test_b8_b9_rows_written_without_grid_use_the_field_default(self):
        declaration = self._generated()
        before = self._values(declaration)
        declaration.write({'b9_line_ids': [Command.create({'ref_number': 'X', 'amount': 40.0})]})
        row = declaration.b9_line_ids
        self.assertEqual(row.grid, 'b9')
        self._assert_values(declaration, {
            '358_10': 40.0, '358_16': before['358_16'] + 40.0, '358_17': before['358_17'] - 40.0, '358_18': before['358_18']})
        declaration.action_generate()
        self._assert_values(declaration, {'358_10': 40.0})
        declaration.write({'b9_line_ids': [Command.delete(row.id)]})
        self._assert_values(declaration, {'358_10': 0.0, '358_16': before['358_16']})
        declaration.write({'b8_line_ids': [Command.create({'ref_number': 'X', 'amount': 40.0})]})
        self.assertEqual(declaration.b8_line_ids.grid, 'b8')

    def test_b5_row_keeps_its_typed_period_when_the_number_changes(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        declaration.write({'b5_line_ids': [Command.create({'grid': 'b5', 'ref_number': '20010/1', 'period': '2026-09-01', 'amount': 5.0})]})
        declaration.b5_line_ids.ref_number = '20010/2'
        self.assertEqual(declaration.b5_line_ids.period, date(2026, 9, 1))

    def test_annex_b4_b5_cap_warnings(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        self._type(declaration, 'tab3_line_ids', {'353_85': 100.0, '353_75': 50.0})
        self.assertIn('row 8 claims 100.00, more than B IV (0.00)', self._warning(declaration, 'row 8 claims'))
        self.assertIn('row 7 claims 50.00, more than B V (0.00)', self._warning(declaration, 'row 7 claims'))
        declaration.write({
            'b4_line_ids': [Command.create({'grid': 'b4', 'ref_number': 'D-1', 'amount': 100.0})],
            'b5_line_ids': [Command.create({'grid': 'b5', 'ref_number': '20010/1', 'amount': 20.0})]})
        self.assertFalse(self._warning(declaration, 'row 8 claims'))
        self.assertIn('row 7 claims 50.00, more than B V (20.00)', self._warning(declaration, 'row 7 claims'))

    def test_annex_b1_and_tab_13_vat_is_checked_against_a1_rows_1_to_3(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        declaration.write({'spec_line_ids': [Command.create({'part': 'spec_sale', 'amount': 50.0})]})
        self.assertIn('carry 50.00 VAT, more than A I rows 1-3 (0.00)', self._warning(declaration, 'B I and tab 13'))
        self._type(declaration, 'tab1_line_ids', {'355_1': 1000.0})
        self.assertFalse(self._warning(declaration, 'B I and tab 13'))

    def test_cell_7_cap_is_the_vat_reduced_in_b1_tab_13_and_b8(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        self._type(declaration, 'tab16_line_ids', {'358_7': 70.0})
        self.assertIn('holds 70.00, more than the VAT reduced in B I, tab 13 and B VIII (0.00)', self._warning(declaration, 'VAT reduced in'))
        declaration.write({
            'invoice_line_ids': [Command.create({'part': 'sale', 'reduce_amount': 30.0})],
            'spec_line_ids': [Command.create({'part': 'spec_sale', 'reduce_amount': 10.0})]})
        self.assertIn('B VIII (40.00)', self._warning(declaration, 'VAT reduced in'))
        declaration.write({'b8_line_ids': [Command.create({'grid': 'b8', 'ref_number': 'P-8', 'amount': 25.0})]})
        self.assertIn('B VIII (65.00)', self._warning(declaration, 'VAT reduced in'))
        self._type(declaration, 'tab16_line_ids', {'358_7': 65.0})
        self.assertFalse(self._warning(declaration, 'VAT reduced in'))

    def test_customs_upload_makes_one_row_per_pdf(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        attachments = self._customs_attachment(number='A1') | self._customs_attachment(number='A2', amount='100.00')
        declaration.action_gec_customs_upload(attachments.ids)
        self.assertEqual(declaration.customs_line_ids.mapped('assessment_number'), ['A1', 'A2'])
        self.assertEqual(declaration.customs_line_ids.attachment_id, attachments)
        self.assertAlmostEqual(declaration.b3_amount, 2361.4)
        for attachment in attachments:
            self.assertEqual(
                (attachment.res_model, attachment.res_id, attachment.company_id),
                (declaration._name, declaration.id, declaration.company_id))
        declaration.action_gec_customs_upload(attachments.ids)
        self.assertEqual(len(declaration.customs_line_ids), 2)

    def test_customs_warnings(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        self.assertFalse(self._warning(declaration, 'B III'))
        attachments = (
            self._customs_attachment(number='A1') | self._customs_attachment(number='A1', issued='16/11/2026')
            | self._customs_attachment(number='A3', amount=''))
        declaration.action_gec_customs_upload(attachments.ids)
        self.assertIn('4522.80 VAT, A III row 2 claims 0.00', self._warning(declaration, 'the customs declarations'))
        self.assertTrue(self._warning(declaration, '%s: the number' % attachments[2].name))
        self.assertIn('A1 is listed 2 times', self._warning(declaration, 'is listed'))
        self.assertIn('A1 is dated %s' % format_date(self.env, date(2026, 11, 16)), self._warning(declaration, 'is dated'))

    def test_customs_upload_refused_when_filed_or_unreadable(self):
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        good = self._customs_attachment()
        broken = self.env['ir.attachment'].create({'name': 'broken.pdf', 'raw': b'not a pdf'})
        with self.assertRaisesRegex(UserError, 'broken.pdf is not a readable PDF'):
            declaration.action_gec_customs_upload((good | broken).ids)
        self.assertFalse(declaration.customs_line_ids)
        self.assertFalse(good.res_model)
        empty = io.BytesIO()
        PdfWriter().write(empty)
        zero_pages = self.env['ir.attachment'].create({'name': 'zero.pdf', 'raw': empty.getvalue()})
        with self.assertRaisesRegex(UserError, 'zero.pdf is not a readable PDF'):
            declaration.action_gec_customs_upload(zero_pages.ids)
        self.assertFalse(declaration.customs_line_ids)
        self.assertFalse(zero_pages.res_model)
        declaration.action_mark_filed()
        with self.assertRaises(UserError):
            declaration.action_gec_customs_upload(good.ids)

    def _chart_ref(self, xmlid):
        record = self.env['account.chart.template'].ref(xmlid, raise_if_not_found=False)
        if not record:
            self.skipTest("%s is not in the test chart of accounts" % xmlid)
        return record

    def test_fixed_asset_column_by_account(self):
        asset = self._chart_ref('ge_account_211310')
        self.env.company.gec_vat_fixed_asset_account_ids = [Command.set(asset.ids)]
        lines = [
            self._prepare_invoice_line(price_unit=price, tax_ids=self.tax_purchase, account_id=account, name='Line')
            for price, account in ((1000.0, asset), (500.0, self.expense))]
        self._create_invoice(
            move_type='in_invoice', partner_id=self.vendor, invoice_date='2026-09-20', post=True,
            invoice_line_ids=lines)
        declaration = self._generated()
        self.assertAlmostEqual(self._line(declaration, '353_15').odoo_value, 180.0)
        self._assert_values(declaration, {'353_15': 180.0, '353_14': 590.0, '353_13': 770.0})

    def test_fixed_asset_column_by_input_vat_account(self):
        self.env.company.gec_vat_fixed_asset_account_ids = [Command.clear()]
        tax = self._chart_ref('ge_tax_p_vat_18_fixed_assets')
        self._invoice('in_invoice', self.vendor, '2026-09-20', 1000.0, tax, self.expense, post=True)
        declaration = self._generated()
        self.assertAlmostEqual(self._line(declaration, '353_15').odoo_value, 180.0)
        self._assert_values(declaration, {'353_15': 180.0, '353_14': 500.0, '353_13': 680.0})

    def test_a3_row_1_vat_without_b2_invoice_is_named(self):
        tax = self._chart_ref('ge_tax_p_vat_18_fixed_assets')
        foreign = self.env['res.partner'].create({'name': 'DE vendor', 'country_id': self.env.ref('base.de').id})
        no_invoice = self._invoice('in_invoice', foreign, '2026-09-20', 2000.0, tax, self.expense, post=True)
        in_b2 = self._invoice('in_invoice', self.vendor, '2026-09-21', 50.0, self.tax_purchase, self.expense, post=True)
        in_b2.write({'rs_einv_series': 'AB', 'rs_einv_number': '54321', 'rs_einv_status': '2'})
        warning = self._warning(self._generated(), 'row 1 holds VAT')
        self.assertIn('%s (360.00)' % no_invoice.name, warning)
        self.assertNotIn(in_b2.name, warning)

    def test_sale_correction_warning_follows_the_replacement_status(self):
        original = self._invoice('out_invoice', self.customer, '2026-10-10', 1000.0, self.tax_sale, self.revenue, post=True)
        replacement = self._invoice('out_invoice', self.customer, '2026-10-12', 1000.0, self.tax_sale, self.revenue, post=True)
        original.write({
            'rs_einv_series': 'AB',
            'rs_einv_number': '100',
            'rs_einv_status': '2',
            'rs_einv_replaced_by_id': replacement.id,
        })
        replacement.write({
            'rs_einv_series': 'AB',
            'rs_einv_number': '101',
            'rs_einv_status': '4',
            'rs_einv_replaces_id': original.id,
            'rs_einv_replacement_mode': 'correction',
        })
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-10-01'})
        declaration.action_generate()
        self.assertIn(replacement.name, self._warning(declaration, 'is posted but not accepted on rs.ge yet'))
        self.assertFalse(self._warning(declaration, 'is accepted on rs.ge but'))
        replacement.write({'rs_einv_status': '8'})
        declaration.action_generate()
        self.assertIn(replacement.name, self._warning(declaration, 'is accepted on rs.ge but'))
        self.assertFalse(self._warning(declaration, 'is posted but not accepted'))

    def test_seed_fixed_asset_accounts_only_when_the_list_is_empty(self):
        xmlids = (
            'ge_account_211210', 'ge_account_211310', 'ge_account_211510', 'ge_account_211420', 'ge_account_211410',
            'ge_account_216990', 'ge_account_210120')
        accounts = self.env['account.account'].concat(*[self._chart_ref(xmlid) for xmlid in xmlids])
        company = self.env.company
        company.gec_vat_fixed_asset_account_ids = [Command.clear()]
        self.env['res.company']._gec_vat_seed_fixed_asset_accounts(company)
        self.assertEqual(company.gec_vat_fixed_asset_account_ids, accounts)
        company.gec_vat_fixed_asset_account_ids = [Command.unlink(accounts[0].id)]
        self.env['res.company']._gec_vat_seed_fixed_asset_accounts(company)
        self.assertEqual(company.gec_vat_fixed_asset_account_ids, accounts[1:])

    def test_audit_report_cell_matches_core(self):
        invoice = self._invoice(
            'out_invoice', self.customer, '2026-09-20', 1000.0, self.tax_sale, self.revenue, post=True)
        bill = self._invoice(
            'in_invoice', self.vendor, '2026-09-21', 1000.0, self.tax_purchase, self.expense, post=True)
        self._invoice('out_invoice', self.customer, '2026-10-10', 1000.0, self.tax_sale, self.revenue, post=True)
        declaration = self._generated()
        for code, sign, move in (('355_1', -1, invoice), ('353_13', 1, bill)):
            cell = self._line(declaration, code)
            action = cell.action_gec_audit()
            self.assertEqual(action['res_model'], 'account.move.line')
            found = self.env['account.move.line'].search(action['domain'])
            self.assertAlmostEqual(sum(found.mapped('balance')), sign * cell.odoo_value, places=2, msg=code)
            self.assertIn(move, found.move_id)
            self.assertTrue(all(date(2026, 9, 1) <= day <= date(2026, 9, 30) for day in found.mapped('date')))

    def test_audit_column_4_and_5_split(self):
        asset = self._chart_ref('ge_account_211310')
        self.env.company.gec_vat_fixed_asset_account_ids = [Command.set(asset.ids)]
        lines = [
            self._prepare_invoice_line(price_unit=price, tax_ids=self.tax_purchase, account_id=account, name='Line')
            for price, account in ((1000.0, asset), (500.0, self.expense))]
        bill = self._create_invoice(
            move_type='in_invoice', partner_id=self.vendor, invoice_date='2026-09-20', post=True,
            invoice_line_ids=lines)
        tax_line = bill.line_ids.filtered('tax_line_id')
        declaration = self._generated()
        Line = self.env['account.move.line']
        column5 = self._line(declaration, '353_15').action_gec_audit()
        self.assertEqual(Line.search(column5['domain']), tax_line)
        self.assertIn("the tax items differ from the cell", column5['name'])
        column4 = self._line(declaration, '353_14').action_gec_audit()
        self.assertIn("column 5 differs from its tax items", column4['name'])
        self.assertIn(tax_line, Line.search(column4['domain']))

    def test_audit_column_4_and_5_add_up(self):
        asset = self._chart_ref('ge_account_211310')
        self.env.company.gec_vat_fixed_asset_account_ids = [Command.set(asset.ids)]
        for price, account in ((1000.0, asset), (500.0, self.expense)):
            self._invoice('in_invoice', self.vendor, '2026-07-20', price, self.tax_purchase, account, post=True)
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-07-01'})
        declaration.action_generate()
        for code in ('353_15', '353_14'):
            cell = self._line(declaration, code)
            action = cell.action_gec_audit()
            self.assertNotIn('differ', action['name'])
            found = self.env['account.move.line'].search(action['domain'])
            self.assertTrue(found)
            self.assertAlmostEqual(sum(found.mapped('balance')), cell.value, places=2, msg=code)

    def test_audit_manual_values_filtered_by_company(self):
        expression = self.env.ref('l10n_ge.tax_report_line_deductible_vat_rc_mechanism_tax')
        other = self.setup_other_company()['company']
        own, foreign = self.env['account.report.external.value'].sudo().create([
            {'name': 'Manual', 'value': 10.0, 'date': '2026-09-15', 'target_report_expression_id': expression.id,
             'company_id': company.id}
            for company in (self.env.company, other)])
        declaration = self._generated()
        action = self._line(declaration, '353_43_1').action_gec_audit()
        self.assertEqual(action['res_model'], 'account.report.external.value')
        self.assertEqual(self.env['account.report.external.value'].sudo().search(action['domain']), own)

    def test_audit_margin_cells(self):
        asset = self._margin_asset('second_hand', 1000.0)
        invoice = self._sale_invoice([1180.0])
        self._sell(asset, invoice.invoice_line_ids)
        declaration = self._generated_august()
        sold = self._line(declaration, '359_1_4').action_gec_audit()
        bought = self._line(declaration, '359_1').action_gec_audit()
        self.assertEqual(self.env['account.move.line'].search(sold['domain']), invoice.invoice_line_ids)
        self.assertEqual(self.env['account.asset'].with_context(**bought['context']).search(bought['domain']), asset)
        self.assertEqual((sold['context']['active_test'], bought['context']['active_test']), (False, False))
        self.assertFalse(self._line(declaration, '359_2_4').action_gec_audit()['domain'][0][2])

    def test_audit_access(self):
        declaration = self._generated()
        groups = self.env.ref('base.group_user') | self.env.ref('account.group_account_readonly')
        other = self.setup_other_company()['company']
        users = {}
        for login, company in (('vat_audit_same', self.env.company), ('vat_audit_other', other)):
            users[login] = self.env['res.users'].create({
                'name': login, 'login': login, 'group_ids': [Command.set(groups.ids)],
                'company_id': company.id, 'company_ids': [Command.set(company.ids)]})
        cell = self._line(declaration, '355_1')
        self.assertEqual(cell.with_user(users['vat_audit_same']).action_gec_audit()['res_model'], 'account.move.line')
        for code in ('353_15', '359_1_4'):
            self._line(declaration, code).with_user(users['vat_audit_same']).action_gec_audit()
        with self.assertRaises(AccessError):
            cell.with_user(users['vat_audit_other']).action_gec_audit()

    def test_auditable_and_formula_flags(self):
        declaration = self._generated()
        self.assertEqual(
            [self._line(declaration, code).auditable for code in ('355_1', '358_4', '358_17')], [True, False, False])
        self.assertFalse(self._line(declaration, '355_1').formula)
        self.assertTrue(self._line(declaration, '358_17').formula)


@tagged('post_install', '-at_install')
class TestGecVatGrid(HttpCase):

    def test_grid_renders_without_owl_error(self):
        # Without the full Accountant app, admin is only an Invoicing user and may not open declarations.
        self.env.ref('base.user_admin').write({
            'group_ids': [Command.link(self.env.ref('account.group_account_user').id)]})
        declaration = self.env['gec.vat.declaration'].create({'date_from': '2026-09-01'})
        action = self.env.ref('gec_vat_declaration.action_gec_vat_declaration')
        url = f'/odoo/action-{action.id}/{declaration.id}?debug=assets'
        wait = """
            const grid = () => document.querySelector('.o_gec_vat_grid');
            const count = (selector) => (grid() ? grid().querySelectorAll(selector).length : 0);
            const wait = async (check, what) => {
                for (let i = 0; i < 100 && !check(); i++) {
                    await new Promise((resolve) => setTimeout(resolve, 100));
                }
                if (!check()) {
                    throw new Error('VAT grid: ' + what);
                }
            };
        """
        self.browser_js(
            url,
            wait + """
                (async () => {
                    await wait(() => count('.o_gvg_table tbody tr') === 22 && count('.o_gvg_padlock') > 0, 'page 1');
                    const pages = [['tab2', 4, 4], ['tab3', 11, 17], ['tab16', 20, 11], ['tab17', 5, 5]];
                    for (const [page, rows, locks] of pages) {
                        document.querySelector('.o_notebook button[name="' + page + '"]').click();
                        await wait(
                            () => count('.o_gvg_table tbody tr') === rows && count('.o_gvg_padlock') === locks,
                            page + ' needs ' + rows + ' rows and ' + locks + ' locks');
                    }
                    const annexes = [['tab6', 7, 'ნაწილი III'], ['tab7', 9, 'ნაწილი IV'], ['tab8', 7, 'ნაწილი V']];
                    for (const [page, heads, title] of annexes) {
                        document.querySelector('.o_notebook button[name="' + page + '"]').click();
                        await wait(
                            () => count('.o_gvr_table thead th') === heads
                                && grid().querySelector('.o_gvg_title').textContent.includes(title),
                            page + ' needs ' + heads + ' header cells');
                    }
                    console.log('VAT grid rendered successfully');
                })();
            """,
            ready='odoo.isReady === true',
            login='admin',
            timeout=60,
            success_signal='VAT grid rendered successfully',
        )
        declaration.action_mark_filed()
        self.browser_js(
            url,
            wait + """
                (async () => {
                    await wait(() => count('.o_gvg_table tbody tr') === 22, 'filed page 1');
                    if (count('input')) {
                        throw new Error('VAT grid: a filed declaration shows an input.');
                    }
                    console.log('VAT grid filed readonly');
                })();
            """,
            ready='odoo.isReady === true',
            login='admin',
            timeout=60,
            success_signal='VAT grid filed readonly',
        )
