# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from datetime import date
from collections import defaultdict

from odoo import models

_logger = logging.getLogger(__name__)


# Sources:
# - Technical Doc https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique
# - "Avis aux débiteurs" https://finances.belgium.be/fr/entreprises/personnel_et_remuneration/avis_aux_debiteurs#q2

class L10n_Be281_10(models.Model):
    _name = 'l10n_be.281_10'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.10 Wizard'

    def _get_declaration_code(self):
        return '281.10'

    def _get_withholding_tag(self):
        return 'f10_2074_bedrijfsvoorheffing'

    def _get_eligible_employees(self, payslips):
        return payslips._l10n_be_filter_remuneration_form('281.10').employee_id

    def _get_overtime_values(self, employee_payslips, year):
        """Box 18: the overtime giving right to the legal overtime premium paid during the year (the payslips of the
        declaration, by fiscal date: a December payslip may be paid in January), never capped,
        and the base of that premium (the hourly wage without the premium), as for the 274.44 and 274.55
        exemptions. The overtime of the hotel industry (CP 302) counts for the limit of 360 hours, the other
        one for the limit of 180 hours. All the overtime work entry types give right to a premium of 50% or
        100%: they are declared with the 57.75% reduction.

        :return: {employee: (hours within the limit of 180 hours, hours within the limit of 360 hours, base)}
        """
        overtime_category = self.env['hr.payslip']._l10n_be_get_overtime_category()
        cp200 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200')
        cp302 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        overtime_values = {}
        for employee, payslips in employee_payslips.items():
            hours_180 = hours_360 = base = 0.0
            for wd in payslips.worked_days_line_ids:
                if overtime_category not in wd.work_entry_type_id.category_ids:
                    continue
                jc = wd.payslip_id.version_id.l10n_be_joint_committee_id
                if not jc:
                    continue
                if jc.is_descendant_of(cp302):
                    hours_360 += wd.number_of_hours
                elif jc.is_descendant_of(cp200):
                    hours_180 += wd.number_of_hours
                else:
                    continue
                rate = wd.work_entry_type_id.amount_rate
                base += wd.amount / rate if rate else 0.0
            overtime_values[employee] = (hours_180, hours_360, base)
        return overtime_values

    def _get_horeca_overtime_values(self, payslips):
        """Box 17: the overtime of the hotel industry paid net, free of ONSS and of withholding tax (voluntary or
        not), declared with their hours. The arrears are declared apart.

        :return: (amount, hours, arrears amount, arrears hours)
        """
        horeca_category = self.env.ref('l10n_be_hr_payroll.HORECA_NET_OVERTIME')
        amount = hours = arrears_amount = arrears_hours = 0.0
        for wd in payslips.worked_days_line_ids.filtered(lambda wd: horeca_category in wd.work_entry_type_id.category_ids):
            if wd.payslip_id.l10n_be_arrear_salary:
                arrears_amount += wd.amount
                arrears_hours += wd.number_of_hours
            else:
                amount += wd.amount
                hours += wd.number_of_hours
        return amount, hours, arrears_amount, arrears_hours

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        year = self.declaration_id.year
        atn_codes = list(self._get_atn_code_mapping())
        cct90_threshold = self.env['hr.rule.parameter']._get_parameter_from_code(
            'cct90_employee_pp_threshold', date=date(int(year), 1, 1), raise_if_not_found=False) or 0

        # The taxable salary is added up from the amounts it is made of, so that each one is declared
        # in the year it is attached to instead of following the aggregate line.
        date_from, date_to = self._get_declaration_period()
        all_payslips = self.env['hr.payslip'].union(employee_payslips.values())
        gross_codes = self.env['hr.payslip']._get_gross_wage_line_codes()
        base_values = {
            code: all_payslips._l10n_be_get_declaration_base(category_code, date_from, date_to)
            for code, category_code in self.env['hr.payslip']._get_gross_wage_base_categories().items()
            if code in gross_codes
        }

        def taxable(code, payslips):
            return sum(base_values[code][p.id] for p in payslips)

        # Box 26h: the commuting reimbursements of the students, recognized by the category of their salary rules
        exempted_commuting = all_payslips._l10n_be_get_declaration_base('EXEMPTED_COMMUTING', date_from, date_to)

        employees = self.env['hr.employee'].browse().union(employee_payslips.keys())
        mobility_budget_total_amount_by_employee = employees._get_l10n_be_mobility_budget_amount_prorated(year=year)
        max_other_transport_exemption = self.env['hr.rule.parameter']._get_parameter_from_code(
                'pricate_car_taxable_threshold',
                date=date(int(year), 1, 1))
        total_employee_contribution = sum(mapped_totals_by_employee[employee].get('GI.EMP.CONT', 0) for employee in mapped_totals_by_employee)

        other_transport_exemption_by_niss = defaultdict(float)
        overtime_values = self._get_overtime_values(employee_payslips, year)

        for employee, mapped_total in mapped_totals_by_employee.items():
            payslips = employee_payslips[employee]

            private_transport_reimbursement = max(0, mapped_total['CAR.PRIV'])
            remaining_exemption = max_other_transport_exemption - private_transport_reimbursement - other_transport_exemption_by_niss[employee.niss]
            company_car_exemption = max(0, min(mapped_total['ATN.CAR'] + mapped_total['ATNCARREGUL'], remaining_exemption))
            other_transport_mean = private_transport_reimbursement + company_car_exemption
            other_transport_exemption_by_niss[employee.niss] += other_transport_mean
            # Box 9a: the non recurring benefits up to the yearly limit, the excess is declared in box 6a. The
            # taxable salary of the bonus payslip is the excess left by the exemption applied on that payslip.
            cct90_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BECCT90')
            cct90_payslip_exemption = -sum(all_line_values['PP_EXEMP'][p.id]['total'] for p in cct90_payslips)
            cct90_bonus = taxable('BONUS_GROSS', cct90_payslips) + cct90_payslip_exemption
            arrear_payslips = payslips.filtered('l10n_be_arrear_salary')
            # Box 19: the voluntary overtime of the recovery plan is declared with the year it was worked in
            relance_amount = defaultdict(float)
            relance_hours = defaultdict(float)
            for p in payslips:
                relance_amount[p.date_from.year] += all_line_values['VOLOTNOONSS'][p.id]['total']
            for wd in payslips.worked_days_line_ids.filtered(lambda wd: wd.code == '039.23'):
                relance_hours[wd.payslip_id.date_from.year] += wd.number_of_hours
            overtime_hours, overtime_hours_360, overtime_base = overtime_values[employee]
            student_payslips = payslips.filtered(lambda p: p.version_id.is_student())
            horeca_amount, horeca_hours, horeca_arrears_amount, horeca_arrears_hours = self._get_horeca_overtime_values(payslips)
            mapped_total.update({
                'mobility_budget': mobility_budget_total_amount_by_employee.get(employee.id, 0),
                'total_gross': sum(taxable(code, payslips) for code in base_values),
                'warrant_gross': taxable('WARRANT_GROSS', payslips.filtered(lambda p: p.struct_id.code == 'BEWARRANT')),
                # Box 7a: only the holiday pay for the services of the year itself is early holiday pay. The holiday
                # pay of the previous year, paid on departure, is ordinary holiday pay declared in box 6a.
                'holiday_gross': taxable('HOLIDAY_TERM_GROSS', payslips.filtered(lambda p: p.struct_id.code == 'BEHOLN')),
                'termination_gross': taxable('TERM_GROSS', payslips.filtered(lambda p: p.struct_id.code == 'BETERM')),
                'cct90_payslip_exemption': cct90_payslip_exemption,
                'cct90_exempted': max(0, min(cct90_bonus, cct90_threshold)),
                # Benefits in kind are declared in 6b, at their gross amount (ONSS included), the ONSS stays deducted from 6a
                'atn_total': sum(mapped_total[code] for code in atn_codes),
                'private_transport_reimbursement': private_transport_reimbursement,
                'arrear_gross': taxable('GROSS', arrear_payslips) - sum(
                    all_line_values[code][p.id]['total'] for code in atn_codes for p in arrear_payslips),
                # Box 20 / 26d: the flexi-job remuneration taken out of the taxable salary by the exemption
                'flexi_exemption': -mapped_total['FLEXI_EXEMPTION'],
                'is_flexi_pensioner': any(p.version_id.l10n_be_early_retirement_status for p in payslips if p.version_id.is_flexi()),
                # Box 26h: the remuneration of the student contracts, already included in the other boxes, taxable
                # or not: the commuting reimbursements are included, the private car one is part of the taxable salary
                'student_remuneration': taxable('GROSS', student_payslips) + sum(
                    exempted_commuting[p.id] for p in student_payslips),
                'relance_amount': relance_amount,
                'relance_hours': relance_hours,
                'overtime_hours': overtime_hours,
                'overtime_hours_360': overtime_hours_360,
                # Box 17: within the limit of 360 hours with a registered cash system, of 300 hours without one
                'horeca_white_cash_register': self.declaration_id.company_id._l10n_be_has_white_cash_register(),
                'horeca_overtime_amount': horeca_amount,
                'horeca_overtime_hours': horeca_hours,
                'horeca_overtime_arrears_amount': horeca_arrears_amount,
                'horeca_overtime_arrears_hours': horeca_arrears_hours,
                'overtime_base': overtime_base,
                'other_transport_mean': other_transport_mean,
                'company_car_exemption': company_car_exemption,
                'total_employee_contribution': total_employee_contribution,
            })
        return mapped_totals_by_employee

    def _get_atn_code_mapping(self):
        return {
            'ATNCARREGUL': '',
            'ATN_HOUSING_FISCAL': 'B',
            'ATN_HEATING': 'C',
            'ATN_ELEC': 'D',
            'ATN.CAR': 'F',
            'ATN.LAP': 'H',
            'ATN.INT': 'I',
            'ATN.TAB': 'J',
            'ATN.PHONE_AMT': 'J',
            'ATN.MOB': 'K',
            'ATN_RENT': 'Z',
            'ATN_PENSION': 'Z',
            'ATN_SOCIAL_CONTRIB': 'Z',
            'ATN_MISC': 'Z',
            'FUEL_CARD_PRIV': 'Z',
        }

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key == "f10_2090_outborderdays":
                    sheet_values[key] = self.env._("%s days", value)
        return super()._post_process_rendering_data_pdf(rendering_data)
