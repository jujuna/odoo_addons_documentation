import io
from collections import defaultdict

import xlsxwriter

from odoo import fields, models
from odoo.tools import BinaryBytes

from .rs_form30_declaration import AUTONOMOUS_REPUBLICS

STYLES = {
    'title': {'bold': True, 'font_size': 14},
    'h2': {'bold': True, 'font_size': 11},
    'header': {'bold': True, 'bg_color': '#EDEFF2', 'bottom': 1, 'text_wrap': True, 'valign': 'top'},
    'text': {'valign': 'top'},
    'wrap': {'text_wrap': True, 'valign': 'top'},
    'muted': {'font_color': '#6B7580', 'italic': True, 'text_wrap': True, 'valign': 'top'},
    'money': {'num_format': '#,##0.00', 'valign': 'top'},
    'rate': {'num_format': '0.##', 'valign': 'top'},
    'int': {'num_format': '0', 'valign': 'top'},
    'percent': {'num_format': '0.##%', 'valign': 'top'},
    'date': {'num_format': 'dd.mm.yyyy', 'valign': 'top'},
    'total': {'bold': True, 'top': 1, 'num_format': '#,##0.00'},
    'total_label': {'bold': True, 'top': 1},
    'link': {'font_color': '#1F4E8C', 'underline': 1, 'valign': 'top'},
    'cell_head': {'bold': True, 'bg_color': '#DDE7F3', 'text_wrap': True, 'valign': 'top'},
    'cell_money': {'bold': True, 'bg_color': '#DDE7F3', 'num_format': '#,##0.00', 'valign': 'top'},
    'flag': {'bold': True, 'font_color': '#B42318', 'text_wrap': True, 'valign': 'top'},
}


class RsForm30DeclarationXlsx(models.Model):
    _inherit = 'rs.form30.declaration'

    explanation_file = fields.Binary(string='Explanation Workbook', readonly=True, copy=False)
    explanation_filename = fields.Char(readonly=True, copy=False)

    def _store_explanation(self):
        self.ensure_one()
        self.write({'explanation_file': BinaryBytes(self._explanation_workbook()), 'explanation_filename': 'form30_explained_%s.xlsx' % self.period})

    def action_export_explanation(self):
        self.ensure_one()
        if self.state != 'exported' or not self.explanation_file:
            self._store_explanation()
        return {
            'type': 'ir.actions.act_url',
            'target': 'self',
            'url': f"/web/content/rs.form30.declaration/{self.id}/explanation_file/{self.explanation_filename}?download=true",
        }

    def _explanation_workbook(self):
        self.ensure_one()
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        styles = {name: book.add_format(spec) for name, spec in STYLES.items()}
        trace = defaultdict(list)
        fresh = self._summary_values(trace)
        rows = {line: index for index, line in enumerate(self._rs_form30_file_lines().sorted(lambda l: (l.date or fields.Date.today(), l.id)), 1)}
        self._xlsx_readme(book, styles)
        self._xlsx_annex_a(book, styles, rows)
        self._xlsx_payslips(book, styles, rows)
        self._xlsx_payments(book, styles, rows)
        self._xlsx_annex_d(book, styles)
        self._xlsx_annex_e(book, styles)
        self._xlsx_main_part(book, styles, fresh)
        self._xlsx_cell_details(book, styles, trace)
        book.close()
        return output.getvalue()

    def _xlsx_table(self, sheet, row, columns, data, styles, totals=()):
        """``columns`` is [(title, width, style key)]; return the next free row."""
        for col, (title, width, _style) in enumerate(columns):
            sheet.set_column(col, col, width)
            sheet.write(row, col, title, styles['header'])
        first = row + 1
        for values in data:
            row += 1
            for col, value in enumerate(values):
                style = styles[columns[col][2]]
                if isinstance(value, tuple):
                    sheet.write_url(row, col, value[1], styles['link'], value[0])
                elif value is None or value == '':
                    sheet.write_blank(row, col, None, style)
                elif columns[col][2] == 'date':
                    sheet.write_datetime(row, col, value, style)
                else:
                    sheet.write(row, col, value, style)
        if totals and data:
            row += 1
            sheet.write(row, 0, self.env._("Total"), styles['total_label'])
            for col in totals:
                letter = xlsxwriter.utility.xl_col_to_name(col)
                sheet.write_formula(row, col, f"=SUM({letter}{first + 1}:{letter}{row})", styles['total'])
        if data:
            sheet.autofilter(first - 1, 0, first - 1 + len(data), len(columns) - 1)
        sheet.freeze_panes(first, 0)
        return row + 2

    def _xlsx_link(self, record, label):
        return (label, f"{self.get_base_url()}/odoo/{record._name}/{record.id}") if record else label

    def _xlsx_category_source(self, partner, on_date):
        history = partner.rs_form30_category_history_ids
        if not history:
            legacy = partner.rs_form30_category_id.name
            return self.env._("Contact category without history: %s", legacy) if legacy else self.env._("No category on the contact")
        entry = history.filtered(lambda h: (not h.date_from or h.date_from <= on_date) and (not h.date_to or on_date <= h.date_to))[:1]
        if not entry:
            return self.env._("Category history has no entry covering %s", on_date)
        return self.env._("Category history: %(category)s, valid %(start)s to %(end)s", category=entry.category_id.name,
            start=entry.date_from or self.env._("always"), end=entry.date_to or self.env._("open"))

    def _xlsx_cells_fed(self, line):
        gross_cell, base_cell = line._main_part_cells()
        cells = [cell for cell in (gross_cell, base_cell) if cell]
        category = line.category_id
        if line.income_type_id.code == '17' and not category.is_organization and not (category.display_code or '').startswith('3.'):
            cells.append('18')
        cells.append('56' if category.is_organization else '39')
        if line.income_type_id.code == '1' and line.autonomous_republic:
            cells.append('57_1' if line.autonomous_republic == 'adjara' else '57_2')
        cells.sort(key=lambda code: (int(code.split('_')[0]), code))
        return ', '.join(cells).replace('_1', '¹').replace('_2', '²')

    def _xlsx_readme(self, book, styles):
        sheet = book.add_worksheet(self.env._("Read me"))
        sheet.set_column(0, 0, 28)
        sheet.set_column(1, 1, 110)
        categories = self.env['rs.form30.category'].search([])
        lines = [
            (self.env._("Declaration"), self.name, 'text'),
            (self.env._("Month"), f"{self.date_from:%d.%m.%Y} – {self.date_to:%d.%m.%Y}", 'text'),
            (self.env._("State"), dict(self._fields['state']._description_selection(self.env))[self.state], 'text'),
            (self.env._("Rows"), self.env._("%(a)s annex A rows, %(d)s annex D rows, %(e)s annex E rows in the file, %(left)s rows left out, %(w)s "
                "rows carry a warning", a=len(self._rs_form30_file_lines()), d=len(self.car_line_ids), e=len(self._rs_form30_file_service_lines()),
                left=self.left_out_count + self.left_out_service_count, w=self.warning_count), 'text'),
            (self.env._("Made on"), f"{fields.Datetime.context_timestamp(self, fields.Datetime.now()):%d.%m.%Y %H:%M}", 'text'),
            (self.env._("Values"), self.env._("Main-part values are the ones stored at the last Generate Lines or Export; the Main part sheet flags "
                "a cell whose stored value differs from a fresh calculation."), 'wrap'),
            ('', '', 'text'),
            (self.env._("Sheets"), '', 'h2'),
            (self.env._("Annex A"), self.env._("Every row of the file the portal imports on page 2, with the amounts Odoo used, the tax behind a "
                "payment row, the payslip behind a salary row, and the main-part cells each row feeds."), 'wrap'),
            (self.env._("Payslips"), self.env._("How each salary row was built: gross, advance pay-outs, income tax and pension from the payslip, "
                "the exemption category and the relief derived from it, the work location that decides cells 57¹ and 57²."), 'wrap'),
            (self.env._("Payments"), self.env._("How each payment row was built: the payment, the bills it settled, the withholding tax and its rate "
                "and income type, the contact category that applied on the payment date, the residency, and whether the row went to annex A or annex "
                "E and why."), 'wrap'),
            (self.env._("Annex D"), self.env._("Company cars used privately, typed by hand on the declaration; the tax follows the engine "
                "band."), 'wrap'),
            (self.env._("Annex E"), self.env._("Service fees to recipients who settle their own income tax; each row names the contact status that "
                "moved it out of annex A."), 'wrap'),
            (self.env._("Main part"), self.env._("All cells 16 to 69 with their value, kind (locked, proposed, typed), status and the formula in "
                "words."), 'wrap'),
            (self.env._("Cell details"), self.env._("One block per cell: every row, journal item or other cell that was added into it, with the "
                "arithmetic and a link to the source record."), 'wrap'),
            ('', '', 'text'),
            (self.env._("Words used"), '', 'h2'),
            (self.env._("Base of a row"), self.env._("amount − pension − other relief, the portal's column 7 − 8 − 9."), 'wrap'),
            (self.env._("Tax of a row"), self.env._("base × rate, the portal's column 12. Salary rows show payroll's own withheld tax next to "
                "it."), 'wrap'),
            (self.env._("Organizations"), '; '.join(categories.filtered('is_organization').mapped('name')) + '. ' + self.env._("Every other category "
                "is a natural person."), 'wrap'),
            (self.env._("Locked cell"), self.env._("Calculated from the annexes at every Generate Lines and Export; the portal computes it the same "
                "way."), 'wrap'),
            (self.env._("Proposed cell"), self.env._("Typed on the portal, but Odoo proposes it from its records and keeps refreshing it until you "
                "type your own value."), 'wrap'),
            (self.env._("Typed cell"), self.env._("Odoo has no source for it: 56¹, 60, 62, 64."), 'wrap'),
            ('', '', 'text'),
            (self.env._("Assumptions"), '', 'h2'),
            ('', self.env._("Rent paid to a non-resident natural person at 20 percent goes to cell 19, because cells 28 to 32 have no 20 percent "
                "line."), 'wrap'),
            ('', self.env._("Cell 58 counts every income account, asset sales included."), 'wrap'),
            ('', self.env._("Cell 63 counts customer payments received in cash journals, not the debit turnover of the cash accounts."), 'wrap'),
            ('', self.env._("Cells 68 and 69 read account 140311 only."), 'wrap'),
            ('', self.env._("Cells 61, 65 and 66 are treated as typed on the portal."), 'wrap'),
        ]
        sheet.write(0, 0, self.env._("Form 30: how every number was built"), styles['title'])
        for row, (label, text, style) in enumerate(lines, 2):
            sheet.write(row, 0, label, styles['h2'] if style == 'h2' else styles['header'] if label and style != 'h2' else styles['text'])
            sheet.write(row, 1, text, styles[style if style != 'h2' else 'text'])

    def _xlsx_annex_a(self, book, styles, rows):
        sheet = book.add_worksheet(self.env._("Annex A"))
        sheet.write(0, 0, self.env._("Annex A: one row per person and payment, exactly what the portal imports"), styles['title'])
        republics = dict(AUTONOMOUS_REPUBLICS)
        sources = dict(self.line_ids._fields['source']._description_selection(self.env))
        data = []
        for line, index in rows.items():
            slip = line.sudo().payslip_id
            source = slip or line.payment_id or line.move_id
            if slip:
                tax_used = self.env._("payroll income tax rule")
                location = slip.version_id.work_location_id
                location_text = ' · '.join(filter(None, [location.name, republics.get(location.rs_form30_autonomous_republic)]))
            else:
                tax = line.withholding_line_id.tax_id
                tax_used = f"{tax.name} ({abs(tax.amount):g}%)" if tax else ''
                location_text = ''
            country = line.country_id
            data.append([index, sources.get(line.source, line.source), f"{line.first_name or ''} {line.last_name or ''}".strip(),
                line.identification or '', f"{country.name} ({country.rs_form30_code})" if country else '', line.category_id.name or '',
                line.income_type_id.name or '', line.date or None, line.amount, line.pension_amount, line.other_relief, line._taxable_base(),
                line.rate, line._portal_tax(), line.tax_amount, line.tax_amount - line._portal_tax(), self._xlsx_cells_fed(line),
                self._xlsx_link(source, source.name if source else ''), tax_used, location_text, line.warning_display or ''])
        columns = [
            ('№', 5, 'int'),
            (self.env._("Source"), 9, 'text'),
            (self.env._("Recipient"), 26, 'wrap'),
            (self.env._("ID number"), 14, 'text'),
            (self.env._("Residency"), 18, 'wrap'),
            (self.env._("Category"), 34, 'wrap'),
            (self.env._("Income type"), 22, 'wrap'),
            (self.env._("Paid on"), 11, 'date'),
            (self.env._("Amount"), 13, 'money'),
            (self.env._("Pension 2%"), 11, 'money'),
            (self.env._("Other relief"), 12, 'money'),
            (self.env._("Base = amount − pension − relief"), 16, 'money'),
            (self.env._("Rate %"), 7, 'rate'),
            (self.env._("Tax = base × rate"), 14, 'money'),
            (self.env._("Withheld in Odoo"), 14, 'money'),
            (self.env._("Difference"), 11, 'money'),
            (self.env._("Feeds cells"), 14, 'text'),
            (self.env._("Source document"), 30, 'link'),
            (self.env._("Tax used"), 34, 'wrap'),
            (self.env._("Work location"), 22, 'wrap'),
            (self.env._("Warnings"), 60, 'muted'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles, totals=(8, 9, 10, 11, 13, 14, 15))

    def _xlsx_payslips(self, book, styles, rows):
        sheet = book.add_worksheet(self.env._("Payslips"))
        sheet.write(0, 0, self.env._("Payslips: how each salary row was built"), styles['title'])
        republics = dict(AUTONOMOUS_REPUBLICS)
        data = []
        for line, index in rows.items():
            slip = line.sudo().payslip_id
            if not slip:
                continue
            totals = defaultdict(float)
            for slip_line in slip.line_ids:
                totals[slip_line.code] += slip_line.total
            advance = sum(slip.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE_PAY').mapped('amount'))
            employee = slip.employee_id
            exemptions = self.env['hr.payroll.tax.exemption'].sudo().search([('employee_ids', 'in', slip._gec_exemption_persons().ids)])
            relief_formula = (self.env._("%(amount)s − pension %(pension)s − %(tax)s / %(rate)s", amount=f"{line.amount:,.2f}",
                                         pension=f"{line.pension_amount:,.2f}", tax=f"{line.tax_amount:,.2f}", rate=f"{line.rate / 100:.2f}")
                              if exemptions else self.env._("no exemption category"))
            version = slip.version_id
            location = version.work_location_id
            contact = employee.work_contact_id
            slip_amount = totals['GROSS'] + advance
            category_source = self._xlsx_category_source(contact, line.date) if contact else self.env._("no work contact")
            if not contact or not (contact.rs_form30_category_history_ids or contact.rs_form30_category_id):
                category_source += self.env._("; defaulted to %s", self.env.ref('gec_income_tax_report.category_4').name)
            data.append([
                index, self._xlsx_link(slip, slip.name), employee.name, f"{slip.date_from:%d.%m.%Y} – {slip.date_to:%d.%m.%Y}",
                line.date, totals['GROSS'], advance, line.amount, -totals['PIT'], totals['ADV_PIT_PRE'], line.tax_amount,
                -totals['PENSION_EE'], totals['ADV_PEE_PRE'], self.env._("yes") if employee.pension_fund_member else self.env._("no"),
                ', '.join(exemptions.mapped('name')), relief_formula, line.other_relief,
                ' · '.join(filter(None, [location.name, republics.get(location.rs_form30_autonomous_republic)])),
                self.env._("employee record") if version.identification_id else self.env._("work contact Tax ID"), contact.name or '',
                category_source,
                (self.env._("work contact: %s", contact.country_id.name) if contact.country_id
                 else self.env._("employee nationality: %s", version.country_id.name) if version.country_id else self.env._("Georgia by default")),
                line.amount / slip_amount if slip_amount else None, line.warning_display or '',
            ])
        columns = [
            (self.env._("Annex A №"), 9, 'int'),
            (self.env._("Payslip"), 38, 'link'),
            (self.env._("Employee"), 24, 'wrap'),
            (self.env._("Period"), 22, 'text'),
            (self.env._("Paid on"), 11, 'date'),
            (self.env._("Gross"), 12, 'money'),
            (self.env._("Advance pay-out"), 12, 'money'),
            (self.env._("Declared amount"), 13, 'money'),
            (self.env._("Income tax"), 12, 'money'),
            (self.env._("Prepaid tax on advances"), 12, 'money'),
            (self.env._("Withheld tax"), 12, 'money'),
            (self.env._("Pension 2%"), 11, 'money'),
            (self.env._("Prepaid pension"), 11, 'money'),
            (self.env._("Pension member"), 9, 'text'),
            (self.env._("Exemption category"), 30, 'wrap'),
            (self.env._("Relief formula"), 28, 'wrap'),
            (self.env._("Relief"), 11, 'money'),
            (self.env._("Work location"), 24, 'wrap'),
            (self.env._("ID number from"), 16, 'wrap'),
            (self.env._("Work contact"), 22, 'wrap'),
            (self.env._("Category source"), 44, 'wrap'),
            (self.env._("Residency from"), 20, 'wrap'),
            (self.env._("Declared share"), 10, 'percent'),
            (self.env._("Row note"), 60, 'muted'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles, totals=(5, 6, 7, 8, 9, 10, 11, 12, 16))

    def _xlsx_payments(self, book, styles, rows):
        sheet = book.add_worksheet(self.env._("Payments"))
        sheet.write(0, 0, self.env._("Payments: how each payment row was built and where it went"), styles['title'])
        company = self.company_id
        data = []
        targets = [(line, self.env._("Annex A row %s", index)) for line, index in rows.items() if line.withholding_line_id]
        targets += [(line, self.env._("Annex E row %s", index)) for index, line in
            enumerate(self._rs_form30_file_service_lines().sorted(lambda l: (l.last_name or '', l.id)), 1) if line.withholding_line_id]
        for line, target in targets:
            withholding = line.withholding_line_id
            payment = withholding.payment_id
            tax = withholding.tax_id
            partner = payment.partner_id
            flags = [label for flag, label in (
                (partner.rs_form30_individual_entrepreneur, self.env._("Individual Entrepreneur")),
                (partner.rs_form30_small_business, self.env._("Small Business Status")),
            ) if flag]
            why = (self.env._("Contact flagged %s: settles their own income tax, so the fee is declared in annex E", ', '.join(flags))
                   if flags else self.env._("Payment carried a withholding line"))
            data.append([self._xlsx_link(payment, payment.name), payment.date,
                dict(payment._fields['state']._description_selection(self.env)).get(payment.state, payment.state), partner.name,
                payment.journal_id.name, payment.amount, payment.currency_id.name, ', '.join(payment.reconciled_bill_ids.mapped('name')), tax.name,
                abs(tax.amount) if tax.amount_type == 'percent' else 0.0, tax.rs_form30_income_type_id.name or '',
                tax.rs_form30_service_type_id.name or '', withholding.base_amount, withholding.amount,
                payment.currency_id._convert(withholding.base_amount, company.currency_id, company, payment.date),
                partner._rs_form30_category_on(payment.date).name or '', self._xlsx_category_source(partner, payment.date),
                f"{partner.country_id.name} ({partner.country_id.rs_form30_code})" if partner.country_id else self.env._("no country on the contact"),
                target, why])
        columns = [
            (self.env._("Payment"), 20, 'link'),
            (self.env._("Date"), 11, 'date'),
            (self.env._("State"), 11, 'text'),
            (self.env._("Paid to"), 26, 'wrap'),
            (self.env._("Journal"), 16, 'wrap'),
            (self.env._("Paid"), 12, 'money'),
            (self.env._("Currency"), 8, 'text'),
            (self.env._("Bills settled"), 24, 'wrap'),
            (self.env._("Withholding tax"), 40, 'wrap'),
            (self.env._("Rate %"), 7, 'rate'),
            (self.env._("Income type"), 22, 'wrap'),
            (self.env._("Service type"), 22, 'wrap'),
            (self.env._("Base"), 12, 'money'),
            (self.env._("Withheld"), 12, 'money'),
            (self.env._("Base in GEL"), 12, 'money'),
            (self.env._("Category applied"), 34, 'wrap'),
            (self.env._("Category source"), 44, 'wrap'),
            (self.env._("Residency"), 20, 'wrap'),
            (self.env._("Declared in"), 16, 'text'),
            (self.env._("Why"), 60, 'wrap'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles, totals=(14,))

    def _xlsx_annex_d(self, book, styles):
        sheet = book.add_worksheet(self.env._("Annex D"))
        sheet.write(0, 0, self.env._("Annex D: company cars used privately, typed on the declaration"), styles['title'])
        data = [[index, car.license_plate or '', f"{car.engine_id.name} ({car.engine_id.amount:g})", car.employee_id.sudo().name or '',
                 car.name or '', car.identification or '', car.amount, car.vehicle_id.sudo().display_name or '']
                for index, car in enumerate(self.car_line_ids, 1)]
        columns = [
            ('№', 5, 'int'),
            (self.env._("Registration number"), 18, 'text'),
            (self.env._("Engine band"), 26, 'wrap'),
            (self.env._("Employee"), 24, 'wrap'),
            (self.env._("Surname, name"), 24, 'wrap'),
            (self.env._("Personal number"), 14, 'text'),
            (self.env._("Tax"), 11, 'money'),
            (self.env._("Vehicle"), 30, 'wrap'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles, totals=(6,))

    def _xlsx_annex_e(self, book, styles):
        sheet = book.add_worksheet(self.env._("Annex E"))
        sheet.write(0, 0, self.env._("Annex E: service fees to recipients who settle their own income tax"), styles['title'])
        data = []
        for index, line in enumerate(self._rs_form30_file_service_lines().sorted(lambda l: (l.last_name or '', l.id)), 1):
            partner = line.partner_id
            flags = [label for flag, label in (
                (partner.rs_form30_individual_entrepreneur, self.env._("Individual Entrepreneur")),
                (partner.rs_form30_small_business, self.env._("Small Business Status")),
            ) if flag]
            tax = line.withholding_line_id.tax_id
            source = line.payment_id or line.move_id
            data.append([index, line.identification or '', line.first_name or '', line.last_name or '', line.address or '',
                         f"{line.country_id.name} ({line.country_id.rs_form30_code})" if line.country_id else '',
                         line.service_type_id.name or self.env._("missing on the tax"), line.amount, ', '.join(flags),
                         self._xlsx_link(source, source.name or ''), tax.name or '', line.warning_display or ''])
        columns = [
            ('№', 5, 'int'),
            (self.env._("ID number"), 14, 'text'),
            (self.env._("First name"), 16, 'wrap'),
            (self.env._("Last name"), 20, 'wrap'),
            (self.env._("Address"), 30, 'wrap'),
            (self.env._("Residency"), 18, 'wrap'),
            (self.env._("Service type"), 30, 'wrap'),
            (self.env._("Amount"), 12, 'money'),
            (self.env._("Recipient status"), 26, 'wrap'),
            (self.env._("Payment or entry"), 20, 'link'),
            (self.env._("Tax on the payment"), 40, 'wrap'),
            (self.env._("Warnings"), 60, 'muted'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles, totals=(7,))

    def _xlsx_main_part(self, book, styles, fresh):
        sheet = book.add_worksheet(self.env._("Main part"))
        sheet.write(0, 0, self.env._("Main part: cells 16 to 69 as stored on the declaration"), styles['title'])
        Explain = self.env['rs.form30.explain']
        formulas = Explain._formulas()
        data = []
        for line in self.summary_line_ids.sorted('sequence'):
            if line.is_section:
                data.append(['', line.name, '', '', '', '', ''])
                continue
            proposal = fresh.get(line.code, False if line.is_boolean else 0.0)
            kind, state, _stale = Explain._cell_state(line, proposal)
            value = (self.env._("Yes") if line.value_bool else self.env._("No")) if line.is_boolean else line.value
            data.append([line.code.replace('_1', '¹').replace('_2', '²'), line.name, line.note or '', value, kind, state,
                formulas.get(line.code, '')])
        columns = [
            (self.env._("Cell"), 7, 'text'),
            (self.env._("Name"), 70, 'wrap'),
            (self.env._("Note"), 24, 'wrap'),
            (self.env._("Value"), 14, 'money'),
            (self.env._("Kind"), 16, 'text'),
            (self.env._("Status"), 46, 'wrap'),
            (self.env._("Formula"), 80, 'wrap'),
        ]
        self._xlsx_table(sheet, 2, columns, data, styles)

    def _xlsx_cell_details(self, book, styles, trace):
        sheet = book.add_worksheet(self.env._("Cell details"))
        sheet.write(0, 0, self.env._("Cell details: what was added into each cell"), styles['title'])
        widths = (8, 46, 52, 40, 14)
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        headers = (self.env._("Cell"), self.env._("Added"), self.env._("Who and what"), self.env._("Arithmetic"), self.env._("Value"))
        for col, title in enumerate(headers):
            sheet.write(2, col, title, styles['header'])
        sheet.freeze_panes(3, 0)
        row = 3
        base_url = self.get_base_url()
        for line in self.summary_line_ids.sorted('sequence'):
            if line.is_section:
                continue
            code = line.code.replace('_1', '¹').replace('_2', '²')
            sheet.write(row, 0, code, styles['cell_head'])
            sheet.write(row, 1, line.name, styles['cell_head'])
            sheet.write(row, 2, '', styles['cell_head'])
            sheet.write(row, 3, '', styles['cell_head'])
            if line.is_boolean:
                sheet.write(row, 4, self.env._("Yes") if line.value_bool else self.env._("No"), styles['cell_head'])
            else:
                sheet.write(row, 4, line.value, styles['cell_money'])
            row += 1
            items = trace.get(line.code, [])
            if not items:
                note = self.env._("Typed by you, nothing added by Odoo") if not (line.computed or line.proposed) else self.env._("No row qualifies")
                sheet.write(row, 1, note, styles['muted'])
                row += 1
            for item in items:
                if item['url']:
                    sheet.write_url(row, 1, base_url + item['url'], styles['link'], item['label'])
                else:
                    sheet.write(row, 1, item['label'], styles['wrap'])
                sheet.write(row, 2, item['detail'], styles['wrap'])
                sheet.write(row, 3, item.get('math', ''), styles['wrap'])
                if item['value'] is None:
                    sheet.write_blank(row, 4, None, styles['money'])
                else:
                    sheet.write(row, 4, item['value'], styles['money'])
                row += 1
            row += 1
