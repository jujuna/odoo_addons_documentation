import io

import xlsxwriter

from odoo import _, fields, models
from odoo.tools import BinaryBytes

STYLES = {
    'title': {'bold': True, 'font_size': 14},
    'h2': {'bold': True, 'font_size': 11},
    'header': {'bold': True, 'bg_color': '#EDEFF2', 'bottom': 1, 'text_wrap': True, 'valign': 'top'},
    'text': {'valign': 'top'},
    'wrap': {'text_wrap': True, 'valign': 'top'},
    'bold_wrap': {'bold': True, 'text_wrap': True, 'valign': 'top'},
    'money': {'num_format': '#,##0.00', 'valign': 'top'},
    'bold_money': {'bold': True, 'num_format': '#,##0.00', 'valign': 'top'},
    'percent': {'num_format': '0.##%', 'valign': 'top'},
    'date': {'num_format': 'dd.mm.yyyy', 'valign': 'top'},
    'flag': {'bold': True, 'font_color': '#B42318', 'text_wrap': True, 'valign': 'top'},
}


class RsCitDeclarationXlsx(models.Model):
    _inherit = 'rs.cit.declaration'

    xlsx_file = fields.Binary(string='Declaration Workbook', readonly=True, copy=False)
    xlsx_filename = fields.Char(readonly=True, copy=False)

    def action_export_xlsx(self):
        """Download the declaration in the rs.ge layout, with the annexes and the journal items behind each row."""
        self.ensure_one()
        self.write({'xlsx_file': BinaryBytes(self._xlsx_workbook()),
                    'xlsx_filename': f"profit_tax_{self.date_from.strftime('%Y_%m')}_v{self.version}.xlsx"})
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': f"/web/content/rs.cit.declaration/{self.id}/xlsx_file/{self.xlsx_filename}?download=true"}

    def _xlsx_workbook(self):
        self.ensure_one()
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        styles = {name: book.add_format(spec) for name, spec in STYLES.items()}
        self._xlsx_main(book, styles)
        self._xlsx_annexes(book, styles)
        self._xlsx_items(book, styles)
        book.close()
        return output.getvalue()

    def _xlsx_rows(self, sheet, row, rows, styles, widths):
        """Write ``rows`` of plain values; a str in a money column is written as text."""
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        for values in rows:
            for col, value in enumerate(values):
                if value is None or value is False:
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    sheet.write_number(row, col, value, styles['money'])
                else:
                    sheet.write(row, col, value, styles['wrap'])
            row += 1
        return row + 1

    def _xlsx_main(self, book, styles):
        sheet = book.add_worksheet(_("Declaration"))
        sheet.write(0, 0, _("Monthly profit tax declaration (form II-086)"), styles['title'])
        status = dict(self._fields['company_status'].selection).get(self.company_status)
        special = dict(self._fields['special_status'].selection).get(self.special_status)
        row = self._xlsx_rows(sheet, 2, [
            (_("Part I"),),
            ('1', _("Taxpayer"), self.company_id.name),
            ('2', _("Identification number"), self.company_id.vat or ''),
            ('3', _("Declaration type"), dict(self._fields['declaration_type'].selection).get(self.declaration_type)),
            ('4', _("Year"), str(self.date_from.year)),
            ('5', _("Month"), str(self.date_from.month)),
            ('6', _("Enterprise status"), status),
            ('', _("Special status (not printed in part I)"), special or ''),
        ], styles, [8, 70, 18, 18])
        sheet.write_row(row, 0, [_("Line"), _("Part III. Profit tax calculation (GEL)"), _("Column 2"),
                                 _("Column 3")], styles['header'])
        row += 1
        for line in self.line_ids:
            bold = line.kind == 'calc'
            sheet.write(row, 0, line.code, styles['bold_wrap' if bold else 'wrap'])
            sheet.write(row, 1, line.name, styles['bold_wrap' if bold else 'wrap'])
            sheet.write_number(row, 2, line.amount, styles['bold_money' if bold else 'money'])
            sheet.write_number(row, 3, line.amount3, styles['bold_money' if bold else 'money'])
            row += 1
        # Part IV is always on the rs.ge form.
        row += 1
        sheet.write(row, 0, _("Part IV. Gambling organisers"), styles['h2'])
        labels = [self._fields[f'g{n}'].help for n in range(1, 6)]
        row = self._xlsx_rows(sheet, row + 1, [
            (str(n), labels[n - 1], self[f'g{n}'], self[f'g{n}_tax']) for n in range(1, 6)
        ] + [('', _("Total"), None, self.gambling_total)], styles, [8, 70, 18, 18])
        if self.checks:
            row += 1
            sheet.write(row, 0, _("Checks"), styles['h2'])
            sheet.merge_range(row + 1, 0, row + 1, 3, self.checks, styles['flag'])

    def _xlsx_annexes(self, book, styles):
        sheet = book.add_worksheet(_("Annexes"))
        row = 0
        widths = [8, 60, 18, 18, 18, 18, 18, 18]

        def section(title, rows, header=None):
            nonlocal row
            sheet.write(row, 0, title, styles['h2'])
            row += 1
            if header:
                sheet.write_row(row, 0, header, styles['header'])
                row += 1
            row = self._xlsx_rows(sheet, row, rows, styles, widths)

        section(_("Annex 1"), [(str(n), self._fields[f'a1_{n}'].string, self[f'a1_{n}']) for n in range(1, 6)])
        section(_("Annex 1.1, part I"), [(str(i), l.name, l.amount1, l.amount2) for i, l in
                                          enumerate(self.annex11_line_ids, 1)],
                ['N', _("Month/year"), _("Line 25.1"), _("Line 16.1.1")])
        section(_("Annex 1.1, parts II and III"),
                [(str(n), '', self[f'a11_{n}']) for n in range(1, 6)] + [('III', '', self.a11_extra)])
        section(_("Annex 1.2"), [(str(i), r.taxed_period, r.taxed_code, r.amount) for i, r in
                                  enumerate(self.recovery_ids, 1)],
                ['N', _("Taxed in period"), _("Taxed on line"), _("Amount")])
        section(_("Annex 1.3"), [(str(n), self._fields[f'a13_{n}'].string, self[f'a13_{n}']) for n in range(1, 6)])
        section(_("Annex 1.4, part I"), [(str(i), l.name, l.amount1, l.amount2) for i, l in
                                          enumerate(self.annex14_line_ids, 1)],
                ['N', _("Month/year"), _("Line 25.3"), _("Line 16.1.2")])
        section(_("Annex 1.4, parts II and III"),
                [(str(n), '', self[f'a14_{n}']) for n in range(1, 6)] + [('III', '', self.a14_extra)])
        section(_("Annex 1.5"), [(str(i), l.name, l.date and l.date.strftime('%d.%m.%Y'), l.amount1) for i, l in
                                  enumerate(self.annex15_line_ids, 1)],
                ['N', _("Tax demand number"), _("Date"), _("Amount")])
        section(_("Annex 1.6"), [(str(i), l.name, l.amount1, l.amount2, l.amount3, l.result1, l.result2)
                                  for i, l in enumerate(self.annex16_line_ids, 1)],
                ['N', _("Year"), _("Net profit"), _("Dividend"), _("Expenses"), _("Reduction"), _("Taxable")])
        section(_("Annex 1.7"), [('', self.a17_1, self.a17_2, self.a17_3, self.a17_4, self.a17_5, self.a17_6)],
                ['', '1', '2', '3', '4', '5', '6'])
        if self.date_from.month == 3:
            section(_("Annex 2"), [('1', _("Inventory at year end"), self.a2_inventory),
                                   ('2', _("Fixed assets at year end"), self.a2_fixed)])
        section(_("Annex 3"), [('', l.name, l.amount1, l.amount2, l.amount3, l.amount4, l.amount5, l.amount6)
                                for l in self.annex3_line_ids],
                ['', '', '1', '2', '3', '4', '5', '6'])
        if self.annex4_line_ids:
            relation = dict(self.env['rs.cit.annex.line']._fields['relation'].selection)
            operation = dict(self.env['rs.cit.annex.line']._fields['operation'].selection)
            documentation = dict(self.env['rs.cit.annex.line']._fields['documentation'].selection)
            section(_("Annex 4"), [(
                l.partner_id.name, l.partner_vat or '', l.partner_country_id.name or '', relation.get(l.relation),
                operation.get(l.operation), l.amount1, l.amount2, l.amount3,
                l.date and l.date.strftime('%d.%m.%Y'), documentation.get(l.documentation),
            ) for l in self.annex4_line_ids], ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])

    def _xlsx_items(self, book, styles):
        sheet = book.add_worksheet(_("Journal Items"))
        header = [_("Line"), _("Date"), _("Entry"), _("Account"), _("Contact"), _("Label"), _("Debit"), _("Credit")]
        sheet.write_row(0, 0, header, styles['header'])
        for col, width in enumerate([8, 12, 22, 32, 28, 40, 14, 14]):
            sheet.set_column(col, col, width)
        row = 1
        for line in self.line_ids.filtered('move_line_ids'):
            for item in line.move_line_ids.sorted(lambda i: (i.date, i.id)):
                sheet.write(row, 0, line.code, styles['text'])
                sheet.write_datetime(row, 1, fields.Datetime.to_datetime(item.date), styles['date'])
                sheet.write(row, 2, item.move_id.name or '', styles['text'])
                sheet.write(row, 3, item.account_id.display_name or '', styles['text'])
                sheet.write(row, 4, item.partner_id.display_name or '', styles['text'])
                sheet.write(row, 5, item.name or '', styles['text'])
                sheet.write_number(row, 6, item.debit, styles['money'])
                sheet.write_number(row, 7, item.credit, styles['money'])
                row += 1
        sheet.freeze_panes(1, 0)
        if row > 1:
            sheet.autofilter(0, 0, row - 1, len(header) - 1)
