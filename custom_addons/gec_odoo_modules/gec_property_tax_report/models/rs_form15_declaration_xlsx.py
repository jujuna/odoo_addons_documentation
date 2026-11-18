import io

from odoo import fields, models
from odoo.tools import BinaryBytes

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - xlsxwriter ships with Odoo
    xlsxwriter = None

STYLES = {
    'title': {'bold': True, 'font_size': 14},
    'heading': {'bold': True, 'font_size': 11, 'bottom': 1},
    'header': {'bold': True, 'bg_color': '#EEECE1', 'border': 1, 'text_wrap': True,
               'valign': 'vcenter'},
    'cell': {'border': 1, 'valign': 'top', 'text_wrap': True},
    'number': {'border': 1, 'num_format': '#,##0.00', 'valign': 'top'},
    'mono': {'border': 1, 'font_name': 'Courier New', 'valign': 'top'},
    'total': {'border': 1, 'bold': True, 'num_format': '#,##0.00'},
    'muted': {'border': 1, 'font_color': '#6F7A86', 'text_wrap': True, 'valign': 'top'},
    'wrap': {'text_wrap': True, 'valign': 'top'},
}


class RsForm15DeclarationXlsx(models.Model):
    """The explanation workbook; every sheet comes from `line._explain()`, as in the dialog."""
    _inherit = 'rs.form15.declaration'

    explanation_file = fields.Binary(string='Explanation Workbook', readonly=True, copy=False)
    explanation_filename = fields.Char(readonly=True, copy=False)

    def action_export_explanation(self):
        self.ensure_one()
        # Only the download slot is written, so a read-only auditor can produce it too.
        self.sudo().write({
            'explanation_file': BinaryBytes(self._explanation_workbook()),
            'explanation_filename': 'form15_explained_%s.xlsx' % self.tax_year,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/explanation_file/%s?download=true' % (
                self._name, self.id, self.explanation_filename),
            'target': 'self',
        }

    def _explanation_workbook(self):
        self.ensure_one()
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True})
        formats = {name: book.add_format(spec) for name, spec in STYLES.items()}
        self._xlsx_readme(book, formats)
        self._xlsx_part3(book, formats)
        self._xlsx_part4(book, formats)
        self._xlsx_details(book, formats)
        book.close()
        return stream.getvalue()

    def _xlsx_readme(self, book, formats):
        _ = self.env._
        sheet = book.add_worksheet(_('Read me'))
        sheet.set_column(0, 0, 34)
        sheet.set_column(1, 1, 96)
        sheet.write(0, 0, _('Property tax declaration, annex V-01'), formats['title'])
        rows = [
            (_('Company'), self.company_id.name),
            (_('Tax year'), self.tax_year),
            (_('Declaration type'), dict(self._fields['kind']._description_selection(self.env)).get(self.kind, '')),
            (_('Months the company existed'), self.months_of_existence or _('full year')),
            (_('Part III rows / tax'), '%s / %s' % (self.part3_count, self.part3_total)),
            (_('Part IV rows / tax'), '%s / %s' % (self.part4_count, self.part4_total)),
            (_('Warnings'), self.warning_count),
            ('', ''),
            (_('Part III'), _('One row per property type and territorial unit; '
                              'named types (1.13, 2, 3, 4, 5.1, 5.2) get one row per asset, '
                              'carrying the asset name in column 2. Column 6 is '
                              '(value at 1 January + value at 31 December) / 2, read from the '
                              'posted depreciation entries.')),
            (_('Part IV'), _('One row per land plot. Column 7 is the rs.ge table value; for '
                             'non-agricultural land it is a municipal coefficient on the '
                             'statutory 0.24 GEL/m², not an amount per square metre.')),
            (_('Derived by rs.ge'), _('Part III columns 11, 13 and 15 and part IV columns 7 and 8 '
                                      'are recomputed by the portal on import. The values here '
                                      'are a cross-check.')),
            (_('Unverified assumptions'), _('Whether column 13 follows column 15 or column 11 when '
                                            'the year is incomplete; whether property type group 5 '
                                            'is leased-out property.')),
        ]
        for index, (label, value) in enumerate(rows, start=2):
            sheet.write(index, 0, label, formats['heading'] if label else formats['wrap'])
            sheet.write(index, 1, value, formats['wrap'])

    def _xlsx_part3(self, book, formats):
        _ = self.env._
        headers = [_('Property (3)'), _('Name (2)'), _('Territorial unit (4)'), _('Year (5)'),
                   _('Average NBV (6)'), _('Coefficient (7)'), _('Exemption (8)'), _('Basis (9)'),
                   _('Rate (10)'), _('Tax (11)'), _('Advance (12)'), _('Difference (13)'),
                   _('Months (14)'), _('For the period (15)'), _('Assets'), _('Warning')]
        sheet = self._xlsx_table(book, formats, _('Part III'), headers)
        for row, line in enumerate(self.part3_line_ids, start=1):
            values = [
                line.property_type_id.name, line.name or '', line.territory_id.name,
                line.acquisition_year_id.name or '', line.average_value,
                line.revaluation_coefficient_id.code or '', line.exemption_amount,
                line.exemption_basis_id.name or '', line.tax_rate, line.tax_amount,
                line.advance_amount, line.difference, line.months_of_existence or '',
                line.prorated_amount, ', '.join(line.with_context(active_test=False).asset_ids.mapped('display_name')),
                line.warning or '',
            ]
            self._xlsx_row(sheet, formats, row, values)

    def _xlsx_part4(self, book, formats):
        _ = self.env._
        headers = [_('Territorial unit (2)'), _('Kind (3)'), _('Area (4)'), _('Taxable area (5)'),
                   _('Basis (6)'), _('Rate (7)'), _('Tax (8)'), _('Unit rate'), _('Plot'), _('Warning')]
        sheet = self._xlsx_table(book, formats, _('Part IV'), headers)
        for row, line in enumerate(self.part4_line_ids, start=1):
            values = [
                line.land_territory_id.name, line.land_type_id.name, line.area,
                line.taxable_area or '', line.exemption_basis_id.name or '', line.rate,
                line.tax_amount, line.land_type_id._unit_rate(line.rate),
                line.plot_id.display_name or '', line.warning or '',
            ]
            self._xlsx_row(sheet, formats, row, values)

    def _xlsx_details(self, book, formats):
        """One block per row, from _explain()."""
        sheet = book.add_worksheet(self.env._('Row details'))
        sheet.set_column(0, 0, 8)
        sheet.set_column(1, 1, 34)
        sheet.set_column(2, 2, 18)
        sheet.set_column(3, 3, 90)
        row = 0
        for part, lines in ((self.env._('Part III'), self.part3_line_ids),
                            (self.env._('Part IV'), self.part4_line_ids)):
            for line in lines:
                trace = line._explain()
                sheet.write(row, 0, part, formats['heading'])
                sheet.write(row, 1, trace['title'], formats['heading'])
                sheet.write(row, 3, trace['formula'], formats['muted'])
                row += 1
                for step in trace['steps']:
                    style = formats['total'] if step.get('total') else formats['cell']
                    sheet.write(row, 0, step['code'], formats['cell'])
                    sheet.write(row, 1, step['label'], formats['cell'])
                    sheet.write(row, 2, step['value'], formats['mono'])
                    sheet.write(row, 3, step['detail'], style)
                    row += 1
                row += 1

    def _xlsx_table(self, book, formats, name, headers):
        sheet = book.add_worksheet(name)
        sheet.freeze_panes(1, 0)
        for column, header in enumerate(headers):
            sheet.write(0, column, header, formats['header'])
            sheet.set_column(column, column, max(14, min(40, len(header) + 6)))
        sheet.autofilter(0, 0, 0, len(headers) - 1)
        return sheet

    def _xlsx_row(self, sheet, formats, row, values):
        for column, value in enumerate(values):
            style = formats['number'] if isinstance(value, float) else formats['cell']
            sheet.write(row, column, value, style)
