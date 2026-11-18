# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import date
import logging

from lxml import etree
from markupsafe import Markup
from stdnum.be.vat import compact as vat_be_compact

from odoo import fields, models
from odoo.fields import Domain
from odoo.addons.l10n_be_hr_payroll.models.l10n_be_281_XX import COUNTRY_CODES, REPORT_CONFIG
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group

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

    def _get_employee_configuration_errors(self, employee):
        """Errors of the configuration of an employee preventing to declare them in the 281 forms.

        :return: list of translated messages, each naming the employee
        """
        errors = []
        # The employees of the branches are declared by the root company
        company = employee.company_id.root_id
        if not (company and company.street and company.zip and company.city and company.phone and company.vat):
            errors.append(self.env._(
                "The company of employee %s is not correctly configured. Please be sure that the following "
                "pieces of information are set: street, zip, city, phone and VAT", employee.name))
        if not (employee.private_street and employee.private_zip and employee.private_city and employee.private_country_id):
            errors.append(self.env._(
                "Employee %s doesn't have a valid private address (with a street, a zip, a city and a country)",
                employee.name))
        elif employee.private_country_id.code not in COUNTRY_CODES:
            errors.append(self.env._(
                "Unsupported country code %(code)s for employee %(employee)s. Please contact an administrator.",
                code=employee.private_country_id.code, employee=employee.name))
        if not employee.version_ids or not employee.version_id:
            errors.append(self.env._("Employee %s has no contract", employee.name))
        if employee.l10n_be_dimona_category != 'alt' and not employee._is_niss_valid():
            errors.append(self.env._("Invalid NISS number for employee %s", employee.name))
        if not employee.l10n_be_legal_first_name or not employee.l10n_be_legal_last_name:
            errors.append(self.env._("Employee %s doesn't have a legal first and last name defined", employee.name))
        return errors

    def _get_declaration_period(self):
        year = int(self.declaration_id.year)
        return date(year, 1, 1), date(year, 12, 31)

    def _get_fiscal_line_domain(self):
        return self.env['hr.payslip']._l10n_be_get_fiscal_line_domain(*self._get_declaration_period())

    def action_generate_declarations(self):
        self.line_ids.unlink()
        for sheet in self:
            all_payslips = self.env['hr.payslip'].search(Domain([
                ('state', 'in', ['validated', 'paid']),
                ('company_id', 'in', sheet.declaration_id.branch_ids.ids),
            ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(*sheet._get_declaration_period()))
            payslips = all_payslips._l10n_be_filter_declared_withholding_taxes()
            sheet.declaration_id.untaxed_employee_ids = (all_payslips - payslips).employee_id
            if sheet._include_untaxed_payslips():
                payslips = all_payslips
            sheet.declaration_id.payslip_ids |= payslips
            eligible_employees = self._get_eligible_employees(payslips)
            sheet.write({
                'line_ids': [(0, 0, {
                    'employee_id': employee.id,
                    'res_model': self._name,
                    'res_id': sheet.id,
                }) for employee in eligible_employees]
            })
        return True

    def _include_untaxed_payslips(self):
        # The payslips without withholding tax (cross-border workers, not the students) are left out of the forms by
        # default
        return False

    def _get_rendering_data(self, employees):
        self.ensure_one()
        self.declaration_id._check_company_configuration()
        return self._get_employees_rendering_data(employees)

    def _get_employees_rendering_data(self, employees):
        """Same as ``_get_rendering_data``, without checking the configuration of the company: the employees whose
        configuration is invalid are left out of the forms and listed in ``employees_with_error``."""
        self.ensure_one()
        all_payslips = self._get_declared_payslips(employees)

        line_codes = self._get_line_codes()
        all_line_values = all_payslips._get_line_values(
            line_codes, vals_list=['total', 'quantity'], extra_domain=self._get_fiscal_line_domain())
        # The employees are numbered (zone 2009) in a stable order, whatever the employees rendered together
        employee_payslips = dict(sorted(all_payslips.grouped('employee_id').items(), key=lambda item: item[0].id))
        return self._generate_employees_data(employee_payslips, all_line_values)

    def _get_declared_payslips(self, employees):
        return self.env['hr.payslip'].search(Domain([
            ('state', 'in', ['validated', 'paid']),
            ('employee_id', 'in', employees.ids),
        ]) & self.env['hr.payslip']._l10n_be_get_fiscal_period_domain(*self._get_declaration_period()))

    def _get_sequence_numbers(self):
        """Sequence number (zone 2009) of the employees of the form, as in the XML file of the declaration: the
        forms follow each other in the order of REPORT_CONFIG, the employees of a form by id.

        The PDF of the employees, generated by batches, show the same number as the XML file (box 1).

        :return: {employee: sequence number}
        """
        self.ensure_one()
        declaration = self.declaration_id
        offset = 0
        for config in REPORT_CONFIG.values():
            sheet = declaration[config['relation_field']][:1]
            if sheet == self:
                break
            if declaration[config['include_field']] and declaration[config['count_field']]:
                offset += len(sheet._get_declared_payslips(sheet.line_ids.employee_id).employee_id)
        employees = self._get_declared_payslips(self.line_ids.employee_id).employee_id.sorted('id')
        return {employee: offset + index for index, employee in enumerate(employees, start=1)}

    def _get_eligible_employees(self, payslips):
        # Return employees that should be included in the declaration.
        income_lines = self._get_income_lines()
        if not income_lines:
            return payslips.employee_id
        return self.env['hr.employee'].union(
            employee for employee, amounts in self._get_income_amounts(payslips, income_lines).items()
            if self._has_declared_income(amounts)
        )

    def _get_income_amounts(self, payslips, income_lines):
        """The amounts of the income lines of each employee, rounded to the cent.

        :return: {employee: list of amounts}
        """
        line_codes = self._get_line_codes()
        all_line_values = payslips._get_line_values(line_codes, extra_domain=self._get_fiscal_line_domain())
        employee_payslips = payslips.grouped('employee_id')
        mapped_totals_by_employee = sum_values_by_group(employee_payslips, all_line_values, line_codes)
        # The income lines may read the values computed for the declaration, as when it is rendered
        mapped_totals_by_employee = self._get_precomputed_employee_data(employee_payslips, all_line_values, mapped_totals_by_employee)
        evaluation_plan = income_lines._get_evaluation_plan()
        income_amounts = {}
        for employee, slips in employee_payslips.items():
            line_values = mapped_totals_by_employee[employee]
            localdict = self._get_localdict(line_values, employee, slips, all_line_values)
            income_amounts[employee] = [
                round(amount, 2) for amount in income_lines._evaluate_batch(localdict, evaluation_plan).values()]
        return income_amounts

    def _has_declared_income(self, amounts):
        return any(amounts)

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
        # The XML file numbers the forms of the whole declaration, the other renderings (PDF) take the same numbers
        sequence = self.env.context.get('starting_sequence', 0)
        sequence_numbers = {} if 'starting_sequence' in self.env.context else self._get_sequence_numbers()
        for employee in employee_payslips:
            is_belgium = employee.private_country_id.code == 'BE'
            sequence += 1

            configuration_errors = self._get_employee_configuration_errors(employee)
            if configuration_errors:
                employees_with_error[employee] = '\n'.join(configuration_errors)
                continue

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
                'f2005_registratienummer': vat_be_compact(self.declaration_id.company_id.vat or ''),
                'f2008_typefiche': self._get_declaration_code().replace('.', ''),
                'f2009_volgnummer': sequence_numbers.get(employee, sequence),
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
        # The zones of the form that the Belcotax schema of the year doesn't define (mapping rows of other years) are
        # not declared in the XML file; the PDF of the form shows them empty
        other_year_values = dict.fromkeys(set(self.env['l10n.be.281.mapping'].search([
            ('declaration_code', '=', self._get_declaration_code()),
        ]).mapped('tag')) - set(mapping_lines.mapped('tag')), 0)
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
        employees_warnings = {}
        for employee, payslips in employee_payslips.items():
            if employee not in base_employees_data:
                continue
            line_values = mapped_totals_by_employee.get(employee, {})
            line_values['entry_date'] = base_employees_data[employee]['entry_date']
            line_values['departure_date'] = base_employees_data[employee]['departure_date']
            localdict = self._get_localdict(
                line_values, employee, payslips, all_line_values, worked_days=worked_days_by_employee[employee])
            sheet_values = mapping_lines._evaluate_batch(localdict, evaluation_plan)
            if warnings := self._check_employee_values(sheet_values, evaluation_plan, line_values):
                employees_warnings[employee] = warnings
            employees_data.append({**other_year_values, **base_employees_data[employee], **sheet_values})

        control_tag = self._get_control_total_tag()
        withholding_tag = self._get_withholding_tag()
        return {
            'base_employees_data': base_employees_data,
            'employees_data': employees_data,
            'employees_with_error': employees_with_error,
            'employees_warnings': employees_warnings,
            'sum_volgnummer': sum_2009,
            'sum_control_total': sum(sheet_values.get(control_tag, 0) for sheet_values in employees_data),
            'sum_withholding': sum(sheet_values.get(withholding_tag, 0) for sheet_values in employees_data),
            'mapping_lines': mapping_lines,
        }

    def _check_employee_values(self, sheet_values, evaluation_plan, line_values):
        """Fix in place the values of the form of an employee that Belcotax would refuse.

        :return: list of warnings explaining what was changed, and what must be declared by hand
        """
        return []

    def _deduct_negative_remuneration(self, remuneration, other_remuneration):
        """Belcotax refuses a negative amount: a negative remuneration of box 6a (a year with only a correction) is
        deducted from the other remunerations of box 6b, as far as they are positive.

        :return: tuple (box 6a, box 6b, positive amount left out of both)
        """
        if remuneration >= 0:
            return remuneration, other_remuneration, 0.0
        deducted = min(-remuneration, max(other_remuneration, 0.0))
        return 0.0, other_remuneration - deducted, -(remuneration + deducted)

    def _reset_negative_amounts(self, sheet_values, evaluation_plan, days_tags=None):
        """Belcotax refuses a negative amount: set the negative amounts to 0, the number of days declared with them
        too, and total the control zones again.

        :param days_tags: {amount tag: tag of its number of days}
        :return: the zones set to 0
        """
        days_tags = days_tags or {}
        reset_tags = [
            tag for _mapping_line, tag, is_monetary, kind, _data in evaluation_plan
            if is_monetary and kind != 'control' and sheet_values[tag] < 0
        ]
        for tag in reset_tags:
            sheet_values[tag] = 0
            if tag in days_tags:
                sheet_values[days_tags[tag]] = 0
        if reset_tags:
            # The plan totals a control zone after the zones it totals
            for _mapping_line, tag, _is_monetary, kind, control_tags in evaluation_plan:
                if kind == 'control':
                    sheet_values[tag] = sum(sheet_values[control_tag] for control_tag in control_tags)
        return [tag.split('_')[1] for tag in reset_tags]

    def _get_declaration_warnings(self):
        """Warnings on the forms of the declared employees, see _check_employee_values. Only the forms that check
        their values render them for it.

        :return: list of messages
        """
        return []

    def _get_employee_values_warnings(self, payslips):
        """Warnings of _check_employee_values on the forms of the declared employees, and on the employees left out
        of the declaration because all their amounts are negative (only the recovery of a previous year).

        :param payslips: the payslips the eligibility of the form is computed on
        """
        self.ensure_one()
        warnings = []
        if self.line_ids:
            rendering_data = self.with_context(round_281=False)._get_rendering_data(self.line_ids.employee_id)
            warnings += [
                self.env._("%(employee)s: %(warning)s", employee=employee.name, warning=warning)
                for employee, employee_warnings in rendering_data['employees_warnings'].items()
                for warning in employee_warnings
            ]
        income_lines = self._get_income_lines()
        if income_lines and payslips:
            warnings += [
                self.env._(
                    "%(employee)s: only negative amounts, no form: declare the recovered amounts by hand.",
                    employee=employee.name)
                for employee, amounts in self._get_income_amounts(payslips, income_lines).items()
                if any(amounts) and not self._has_declared_income(amounts)
            ]
        return warnings

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
