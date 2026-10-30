# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import date
import logging

from lxml import etree
from markupsafe import Markup
from stdnum.be.vat import compact as vat_be_compact

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.addons.l10n_be_hr_payroll.models.l10n_be_281_XX import COUNTRY_CODES
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Sources:
# - Technical Doc https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique
# - "Avis aux débiteurs" https://finances.belgium.be/fr/entreprises/personnel_et_remuneration/avis_aux_debiteurs#q2


class L10n_Be281_Mixin(models.AbstractModel):
    _name = 'l10n_be.281.mixin'
    _inherit = ['hr.payroll.declaration.mixin']
    _description = 'HR Payroll 281 Declaration Mixin'

    declaration_id = fields.Many2one('l10n_be.281_xx', index=True, ondelete='cascade')

    def _country_restriction(self):
        return 'BE'

    def _get_lang_code(self, lang):
        return self.declaration_id._get_lang_code(lang)

    def _get_country_code(self, country):
        return self.declaration_id._get_country_code(country)

    @api.model
    def _check_employees_configuration(self, employees):
        invalid_employees = employees.filtered(lambda e: not (e.company_id and e.company_id.street and e.company_id.zip and e.company_id.city and e.company_id.phone and e.company_id.vat))
        if invalid_employees:
            raise UserError(self.env._("The company is not correctly configured on your employees. Please be sure that the following pieces of information are set: street, zip, city, phone and vat") + '\n' + '\n'.join(invalid_employees.mapped('name')))

        invalid_employees = employees.filtered(
            lambda e: not e.private_street or not e.private_zip or not e.private_city or not e.private_country_id)
        if invalid_employees:
            raise UserError(self.env._("The following employees don't have a valid private address (with a street, a zip, a city and a country):\n%s", '\n'.join(invalid_employees.mapped('name'))))

        invalid_employees = employees.filtered(lambda emp: not emp.version_ids or not emp.version_id)
        if invalid_employees:
            raise UserError(self.env._('Some employee has no contract:\n%s', '\n'.join(invalid_employees.mapped('name'))))

        invalid_employees = employees.filtered(lambda e: e.l10n_be_dimona_category != 'alt' and not e._is_niss_valid())
        if invalid_employees:
            raise UserError(self.env._('Invalid NISS number for those employees:\n %s', '\n'.join(invalid_employees.mapped('name'))))

        invalid_employees = employees.filtered(lambda e: not e.l10n_be_legal_first_name or not e.l10n_be_legal_last_name)
        if invalid_employees:
            raise UserError(self.env._("The following employees don't have a legal first and last name defined:\n %s", '\n'.join(invalid_employees.mapped('name'))))

        invalid_country_codes = employees.private_country_id.filtered(lambda c: c.code not in COUNTRY_CODES)
        if invalid_country_codes:
            raise UserError(self.env._('Unsupported country code %s. Please contact an administrator.', ', '.join(invalid_country_codes.mapped('code'))))

    def _get_declaration_period(self):
        year = int(self.declaration_id.year)
        return date(year, 1, 1), date(year, 12, 31)

    def _get_fiscal_line_domain(self):
        return self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(*self._get_declaration_period())

    def action_generate_declarations(self):
        self.line_ids.unlink()
        for sheet in self:
            company_id = sheet.declaration_id.company_id
            all_payslips = self.env['hr.payslip'].search(Domain([
                ('state', 'in', ['validated', 'paid']),
                ('company_id', '=', company_id.id),
                ('employee_id.l10n_be_dimona_category', '!=', 'alt'),
            ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(*sheet._get_declaration_period()))
            payslips = all_payslips.filtered(lambda p: not p.version_id.no_withholding_taxes)
            sheet.declaration_id.payslip_ids |= payslips
            sheet.declaration_id.untaxed_employee_ids = (all_payslips - payslips).employee_id
            eligible_employees = self._get_eligible_employees(payslips)
            sheet.write({
                'line_ids': [(0, 0, {
                    'employee_id': employee.id,
                    'res_model': self._name,
                    'res_id': sheet.id,
                }) for employee in eligible_employees]
            })
        return True

    def _get_rendering_data(self, employees):
        self.ensure_one()
        self.declaration_id._check_company_configuration()

        all_payslips = self.env['hr.payslip'].search(Domain([
            ('state', 'in', ['validated', 'paid']),
            ('employee_id', 'in', employees.ids),
        ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(*self._get_declaration_period()))
        all_employees = all_payslips.employee_id
        self._check_employees_configuration(all_employees)

        line_codes = self._get_line_codes()
        all_line_values = all_payslips._get_line_values(
            line_codes, vals_list=['total', 'quantity'], extra_domain=self._get_fiscal_line_domain())
        employee_payslips = all_payslips.grouped('employee_id')
        return self._generate_employees_data(employee_payslips, all_line_values)

    def _get_eligible_employees(self, payslips):
        # Return employees that should be included in the declaration.
        income_lines = self._get_income_lines()
        if not income_lines:
            return payslips.employee_id
        line_codes = self._get_line_codes()
        all_line_values = payslips._get_line_values(line_codes, extra_domain=self._get_fiscal_line_domain())
        employee_payslips = payslips.grouped('employee_id')
        mapped_totals_by_employee = sum_values_by_group(employee_payslips, all_line_values, line_codes)
        evaluation_plan = income_lines._get_evaluation_plan()
        eligible_employees = self.env['hr.employee']
        for employee, slips in employee_payslips.items():
            line_values = mapped_totals_by_employee[employee]
            localdict = self._get_localdict(line_values, employee, slips, all_line_values)
            if any(round(amount, 2) for amount in income_lines._evaluate_batch(localdict, evaluation_plan).values()):
                eligible_employees |= employee
        return eligible_employees

    def _get_income_lines(self):
        return self.env['l10n.be.281.mapping']

    def _get_withholding_amount(self):
        # Total withholding taxes declared by this form, in euros.
        self.ensure_one()
        rendering_data = self.with_context(round_281=False)._get_rendering_data(self.line_ids.employee_id)
        return rendering_data['sum_withholding']

    def _get_withholding_tag(self):
        raise NotImplementedError("Child models must define the tag of their withholding taxes.")

    def _get_control_total_tag(self):
        # Zone 2059: the control total of the form, the total of its amounts
        return f"f{self._get_declaration_code().split('.')[1]}_2059_totaalcontrole"

    def _get_withholding_amounts(self):
        """Withholding taxes declared by this form for each employee, in euros.

        :return: tuple ({employee: amount}, {employee left out of the form: error message})
        """
        self.ensure_one()
        rendering_data = self.with_context(round_281=False)._get_rendering_data(self.line_ids.employee_id)
        tag = self._get_withholding_tag()
        amounts = {sheet_values['employee']: sheet_values[tag] for sheet_values in rendering_data['employees_data']}
        return amounts, rendering_data['employees_with_error']

    def _to_eurocent(self, amount):
        # Moved to l10n.be.281.mapping, but some other reports still expect this method to exist here.
        return self.env['l10n.be.281.mapping']._to_eurocent(amount)

    def _get_line_codes(self):
        return list(set(self.env['hr.salary.rule'].with_context(active_test=False).search([]).mapped('code')))

    def _get_declaration_code(self):
        raise NotImplementedError("Child models must define their declaration code.")

    def _get_mapping_lines(self, year):
        self.ensure_one()
        return self.env['l10n.be.281.mapping'].search([
            ('declaration_code', '=', self._get_declaration_code()),
            ('date_from', '<=', date(int(year), 1, 1)),
            '|', ('date_to', '=', False), ('date_to', '>=', date(int(year), 12, 31)),
        ])

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        return mapped_totals_by_employee

    def _get_atn_code_mapping(self):
        return {}

    def _generate_employees_data(self, employee_payslips, all_line_values):
        self.ensure_one()
        base_employees_data = {}
        employees_with_error = {}
        sequence = self.env.context.get('starting_sequence', 0)
        for employee in employee_payslips:
            is_belgium = employee.private_country_id.code == 'BE'
            sequence += 1

            postcode = employee.private_zip.strip() if is_belgium else '0'
            if len(postcode) > 4 or not postcode.isdecimal():
                employees_with_error[employee] = self.env._("The belgian postcode length shouldn't exceed 4 characters and should contain only numbers for employee %s", employee.name)
                continue

            # Box 4: the legal names of the employee, the display name may hold anything else (nickname, login...)
            first_name, last_name = (name.strip() for name in employee._get_split_name())
            if len(first_name) > 30:
                employees_with_error[employee] = self.env._("The employee first name shouldn't exceed 30 characters for employee %s", employee.name)
                continue

            year_end = date(int(self.declaration_id.year), 12, 31)
            first_contract_date = employee._get_first_contract_date(date_limit=year_end)
            if not first_contract_date:
                employees_with_error[employee] = self.env._("No first contract date found for employee %s", employee.name)
                continue
            # Box 2: the entry date if the employee started during the year, the departure date if the employee
            # wasn't employed anymore on December 31
            departure_date = employee.departure_date

            sheet_values = {
                'employee': employee,
                'employee_id': employee.id,
                'entry_date': first_contract_date.strftime('%d-%m-%Y') if first_contract_date.year == year_end.year else '',
                'departure_date': departure_date.strftime('%d-%m-%Y') if departure_date and first_contract_date < departure_date < year_end else '',
                'f2002_inkomstenjaar': self.declaration_id.year,
                'f2005_registratienummer': vat_be_compact(self.declaration_id.company_id.vat),
                'f2008_typefiche': self._get_declaration_code().replace('.', ''),
                'f2009_volgnummer': sequence,
                'f2011_nationaalnr': employee.niss,
                'f2013_naam': last_name,
                'f2015_adres': employee.private_street,
                'f2016_postcodebelgisch': postcode,
                'employee_city': employee.private_city,
                'f2018_landwoonplaats': '150' if is_belgium else self._get_country_code(employee.private_country_id),
                'f2027_taalcode': self._get_lang_code(employee.lang),
                'f2028_typetraitement': self.declaration_id.type_treatment,
                'f2029_enkelopgave325': 0,
                'f2112_buitenlandspostnummer': employee.private_zip if not is_belgium else '0',
                'f2114_voornamen': first_name,
            }

            # Le code postal belge (2016) et le code postal étranger (2112) ne peuvent jamais être remplis tous les deux.
            # Ils ne peuvent pas non plus être vides tous les deux.
            if is_belgium:
                sheet_values.pop('f2112_buitenlandspostnummer')
            else:
                sheet_values.pop('f2016_postcodebelgisch')

            base_employees_data[employee] = sheet_values

        sum_2009 = sum(sheet_values['f2009_volgnummer'] for sheet_values in base_employees_data.values())

        year = self.declaration_id.year
        mapping_lines = self._get_mapping_lines(year)
        line_codes = self._get_line_codes()
        all_worked_days = {}
        if mapping_lines:
            work_entry_type_codes = self.env['hr.work.entry.type'].with_context(active_test=False).search([]).mapped('code')
            all_worked_days = self.env['hr.payslip'].union(employee_payslips.values())._get_worked_days_line_values(
                work_entry_type_codes, ['number_of_days'])
        employees_data = []
        valid_employee_payslips = {
            employee: payslips for employee, payslips in employee_payslips.items() if employee not in employees_with_error
        }
        mapped_totals_by_employee = sum_values_by_group(valid_employee_payslips, all_line_values, line_codes)
        worked_days_by_employee = sum_values_by_group(
            valid_employee_payslips, all_worked_days, list(all_worked_days), 'number_of_days')
        mapped_totals_by_employee = self._get_precomputed_employee_data(employee_payslips, all_line_values, mapped_totals_by_employee)
        evaluation_plan = mapping_lines._get_evaluation_plan()
        for employee, payslips in employee_payslips.items():
            if employee not in base_employees_data:
                continue
            line_values = mapped_totals_by_employee.get(employee, {})
            line_values['entry_date'] = base_employees_data[employee]['entry_date']
            line_values['departure_date'] = base_employees_data[employee]['departure_date']
            localdict = self._get_localdict(
                line_values, employee, payslips, all_line_values, worked_days=worked_days_by_employee[employee])
            sheet_values = mapping_lines._evaluate_batch(localdict, evaluation_plan)
            employees_data.append({**base_employees_data[employee], **sheet_values})

        control_tag = self._get_control_total_tag()
        withholding_tag = self._get_withholding_tag()
        return {
            'base_employees_data': base_employees_data,
            'employees_data': employees_data,
            'employees_with_error': employees_with_error,
            'sum_volgnummer': sum_2009,
            'sum_control_total': sum(sheet_values.get(control_tag, 0) for sheet_values in employees_data),
            'sum_withholding': sum(sheet_values.get(withholding_tag, 0) for sheet_values in employees_data),
            'mapping_lines': mapping_lines,
        }

    def _get_pdf_report(self):
        return self.env.ref(f"l10n_be_hr_payroll.action_report_employee_{self._get_declaration_code().replace('.', '_')}")

    def _get_pdf_filename(self, employee):
        self.ensure_one()
        return self.env._(
            '%(year)s-%(employee)s-%(form)s',
            year=self.declaration_id.year, employee=employee.name, form=self._get_declaration_code().replace('.', '_'))

    def _post_process_rendering_data_pdf(self, rendering_data):
        result = {}
        data = self.declaration_id._get_main_data()
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if isinstance(value, int) and value == 0:
                    sheet_values[key] = '0.00 €'
                elif isinstance(value, float):
                    sheet_values[key] = f'{value:,.2f} €'
                elif not value:
                    sheet_values[key] = self.env._('None')
            result[sheet_values['employee']] = {**sheet_values, **data}
        return result

    def _get_localdict(self, line_values, employee=None, payslips=None, all_line_values=None, worked_days=None):
        return self.env['l10n.be.281.mapping']._get_localdict(
            line_values=line_values,
            employee=employee or self.env['hr.employee'],
            payslips=payslips or self.env['hr.payslip'],
            all_line_values=all_line_values or {},
            worked_days=defaultdict(float, worked_days or {}),
            atn_mapping=self._get_atn_code_mapping(),
            _to_eurocent=self._to_eurocent,
        )

    def _get_xml_declaration_fields_markup(self, employee_data, lines):
        # Built with lxml, not a QWeb t-foreach: QWeb can't set an element's tag name dynamically.
        self.ensure_one()
        skip_if_falsy_tags = set(lines.filtered('skip_if_falsy').mapped('tag'))
        tags = sorted(lines.mapped('tag'), key=lambda tag: int(tag.split('_')[1]))
        root = etree.Element('root')
        for tag in tags:
            value = employee_data[tag]
            if tag in skip_if_falsy_tags and not value:
                continue
            etree.SubElement(root, tag).text = str(value)
        # PY014: lxml's tostring already XML-escapes this text, so Markup wraps escaped content, not raw.
        return Markup('').join(
            Markup(etree.tostring(child, encoding='unicode')) for child in root
        )
