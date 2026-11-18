# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from datetime import date
from collections import defaultdict

from odoo import models
from odoo.addons.l10n_be_hr_payroll.models.utils import sum_values_by_group
from odoo.tools import format_amount

_logger = logging.getLogger(__name__)

# The zones of the 281.10 holding a number of hours (boxes 17, 18 and 19), not an amount
HOURS_TAGS = frozenset({
    'f10_2095_aantaluren',
    'f10_2097_aantaluren',
    'f10_2110_aantaloveruren360',
    'f10_2118_overtimehours180',
    'f10_2138_covidovertimehours2023',
    'f10_2142_totalovertimehours180',
    'f10_2167_aantaloveruren300horeca',
    'f10_2168_achterstallaantaloveruren300horeca',
    'f10_2169_aantaloveruren360horeca',
    'f10_2170_achterstallaantaloveruren360horeca',
    'f10_2176_overtimehours180',
    'f10_2196_relanceovertimehours',
    'f10_2209_overtimehours',
    'f10_2228_relanceovertimehours2025',
})


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

    def _include_untaxed_payslips(self):
        # The cross-border workers, whose remuneration is taxed in their country of residence without Belgian
        # withholding tax, get a 281.10 as well (French cross-border workers: "avis aux débiteurs", p. 14)
        return True

    def _get_eligible_employees(self, payslips):
        payslips = payslips._l10n_be_filter_remuneration_form('281.10')
        # A form is created for the employees with a remuneration (or a withholding tax) to declare. A form holding
        # only the contributions withheld is created only when the employee has no 281.18: if he has one, its amounts
        # are transferred to it (_get_amounts_to_transfer_to_281_18). A form holding nothing (payslips without any
        # amount, as the one of a month without work) is not created.
        line_codes = self._get_line_codes()
        all_line_values = payslips._get_line_values(
            line_codes, vals_list=['total', 'quantity'], extra_domain=self._get_fiscal_line_domain())
        employee_payslips = payslips.grouped('employee_id')
        mapped_totals_by_employee = sum_values_by_group(employee_payslips, all_line_values, line_codes)
        mapped_totals_by_employee = self._get_precomputed_employee_data(employee_payslips, all_line_values, mapped_totals_by_employee)
        contributions = self._get_contributions_without_remuneration(mapped_totals_by_employee)
        transferred_employees = self._get_employees_with_281_18(employee_payslips, contributions)
        return self.env['hr.employee'].union(
            employee for employee, mapped_total in mapped_totals_by_employee.items()
            if mapped_total['has_remuneration'] or round(mapped_total.get('PPTOTAL', 0), 2)
            or (employee in contributions and employee not in transferred_employees)
        )

    def _get_amounts_to_transfer_to_281_18(self, employee_payslips, all_line_values):
        """The amounts of the 281.10 of the employees without any remuneration declared on it, when they have a 281.18:
        the special social security contribution (code 287, zone 2071 of the 281.18), the personal contributions to the
        group insurance (zone 2068), the individual continuation (2069) and the free supplementary pension (2128). The
        social secretariat transfers them to the 281.18 of the employee if he has one, and creates no 281.10 (CSS9V).
        Without a 281.18, they stay on a 281.10 holding only them.

        :return: {employee: {'special_contribution': x, 'group_insurance': x, 'individual_continuation': x,
                             'free_pension': x}}, positive amounts in euros
        """
        line_codes = self._get_line_codes()
        mapped_totals_by_employee = sum_values_by_group(employee_payslips, all_line_values, line_codes)
        mapped_totals_by_employee = self._get_precomputed_employee_data(employee_payslips, all_line_values, mapped_totals_by_employee)
        contributions = self._get_contributions_without_remuneration(mapped_totals_by_employee)
        transferred_employees = self._get_employees_with_281_18(employee_payslips, contributions)
        return {employee: amounts for employee, amounts in contributions.items() if employee in transferred_employees}

    def _get_employees_with_281_18(self, employee_payslips, employees):
        """The employees among ``employees`` with a 281.18 of their own in the declaration (an amount to declare on it,
        the amounts transferred from the 281.10 aside)."""
        sheet_281_18 = self.declaration_id.l10n_be_281_18_ids[:1]
        payslips = self.env['hr.payslip'].union(employee_payslips[employee] for employee in employees)
        if not sheet_281_18 or not payslips:
            return set()
        return sheet_281_18._get_employees_with_own_form(payslips)

    def _get_contributions_without_remuneration(self, mapped_totals_by_employee):
        """The contributions withheld from the employees without any remuneration declared on the 281.10, to transfer
        to their 281.18 (see _get_amounts_to_transfer_to_281_18).

        :return: {employee: {'special_contribution': x, 'group_insurance': x, 'individual_continuation': x,
                             'free_pension': x}}, positive amounts in euros, only the employees with an amount
        """
        result = {}
        for employee, mapped_total in mapped_totals_by_employee.items():
            if mapped_total['has_remuneration']:
                continue
            amounts = {
                'special_contribution': -mapped_total['M.ONSS'],
                'group_insurance': mapped_total['GI.EMP.CONT'] + mapped_total['GI.EMP.VOL'],
                # not computed by Odoo, declared at 0 on the 281.10
                'individual_continuation': 0.0,
                'free_pension': 0.0,
            }
            if any(round(amount, 2) for amount in amounts.values()):
                result[employee] = amounts
        return result

    def _get_overtime_values(self, employee_payslips, year):
        """Box 18: the overtime giving right to the legal overtime premium paid during the year (the payslips of the
        declaration, by fiscal date: a December payslip may be paid in January), never capped,
        and the base of that premium (the hourly wage without the premium), as for the 274.44 and 274.55
        exemptions. The overtime of the hotel industry (CP 302) counts for the limit of 360 hours, the one of all
        the other employers for the limit of 180 hours. The base and the hours are declared with the reduction of
        66.81% (premium from 20% to 50%) or of 57.75% (premium of 50% or more), as the payslip reduces the
        withholding tax (P.P.DEDEH); a premium under 20%, or none (overtime paid at 100%), gives right to no
        reduction (see hr.payslip._is_extra_hours_qualifying).

        :return: {employee: {'overtime_hours': hours within the limit of 180 hours,
                             'overtime_hours_360': hours within the limit of 360 hours,
                             'overtime_base': base at 57.75%, 'overtime_rate_hours': hours at 57.75%,
                             'overtime_base_6681': base at 66.81%, 'overtime_hours_6681': hours at 66.81%}}
        """
        Payslip = self.env['hr.payslip']
        cp302 = self.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_302')
        date_from, date_to = self._get_declaration_period()
        overtime_values = {}
        for employee, payslips in employee_payslips.items():
            values = dict.fromkeys((
                'overtime_hours', 'overtime_hours_360', 'overtime_base', 'overtime_rate_hours',
                'overtime_base_6681', 'overtime_hours_6681'), 0.0)
            for wd in payslips._l10n_be_get_attached_worked_days(date_from, date_to):
                if not Payslip._is_extra_hours_qualifying(wd.work_entry_type_id):
                    continue
                jc = wd.payslip_id.version_id.l10n_be_joint_committee_id
                if wd.payslip_id.version_id._l10n_be_is_company_director():
                    # the company directors are declared on the 281.20
                    continue
                # Without rate (the overtime to recover of the databases installed before its rate was set), the
                # overtime has the premium of 50%
                premium_rate = Payslip._l10n_be_get_overtime_premium_rate(wd.work_entry_type_id)
                if jc and jc.is_descendant_of(cp302):
                    values['overtime_hours_360'] += wd.number_of_hours
                else:
                    values['overtime_hours'] += wd.number_of_hours
                if 0.2 <= premium_rate < 0.5:
                    values['overtime_base_6681'] += wd._l10n_be_get_overtime_base()
                    values['overtime_hours_6681'] += wd.number_of_hours
                else:
                    values['overtime_base'] += wd._l10n_be_get_overtime_base()
                    values['overtime_rate_hours'] += wd.number_of_hours
            overtime_values[employee] = values
        return overtime_values

    def _get_horeca_overtime_values(self, payslips):
        """Box 17: the overtime of the hotel industry paid net, free of ONSS and of withholding tax (voluntary or
        not), declared with their hours. The arrears are declared apart. The limit of 360 hours applies to the hours
        worked for a company with a registered cash system (the company of the payslip, a branch may have one), the
        one of 300 hours to the others.

        The hours beyond the yearly limit, in the order they were worked, don't enter into account for the
        exemption: they are declared as remuneration (box 6a).

        :return: {'horeca_overtime_<amount|hours|arrears_amount|arrears_hours>_<300|360>': value,
                  'horeca_overtime_excess': amount beyond the limit}
        """
        # called for each employee: the id is cached, env.ref would check its existence
        horeca_category = self.env['hr.salary.rule.category'].browse(
            self.env['ir.model.data']._xmlid_to_res_id('l10n_be_hr_payroll.HORECA_NET_OVERTIME'))
        values = {
            f'horeca_overtime_{key}_{limit}': 0.0
            for key in ('amount', 'hours', 'arrears_amount', 'arrears_hours') for limit in (300, 360)
        }
        values['horeca_overtime_excess'] = 0.0
        date_from, date_to = self._get_declaration_period()
        worked_days = payslips._l10n_be_get_attached_worked_days(date_from, date_to)
        consumed_hours = 0.0
        for wd in worked_days.filtered(lambda wd: horeca_category in wd.work_entry_type_id.category_ids).sorted(
                lambda wd: (wd.payslip_id.date_from, wd.payslip_id.id, wd.id)):
            white_cash_register = wd.payslip_id.company_id._l10n_be_has_white_cash_register()
            limit = 360 if white_cash_register else 300
            threshold = self.env['hr.rule.parameter']._get_parameter_from_code(
                f"cp302_net_overtime_threshold_{'' if white_cash_register else 'not_'}white_cash_register",
                date_to, raise_if_not_found=False)
            hours = wd.number_of_hours
            if threshold:
                hours = max(0.0, min(hours, threshold - consumed_hours))
            amount = wd.amount * hours / wd.number_of_hours if wd.number_of_hours else wd.amount
            consumed_hours += hours
            values['horeca_overtime_excess'] += wd.amount - amount
            prefix = 'arrears_' if wd.payslip_id.l10n_be_arrear_salary else ''
            values[f'horeca_overtime_{prefix}amount_{limit}'] += amount
            values[f'horeca_overtime_{prefix}hours_{limit}'] += hours
        return values

    def _get_holiday_pay_regularization(self, payslips, all_line_values):
        """The regularization of the simple holiday pay of the previous employer (HolPayReg) of the termination fees
        payslips, net of the ONSS paid on it: the part of their taxable salary it accounts for."""
        amount = 0.0
        for payslip in payslips:
            regularization = all_line_values['HolPayReg'][payslip.id]['total']
            if regularization:
                onss_rate = sum(payslip.line_ids.filtered(lambda line: line.code == 'ONSS_TERM').mapped('rate'))
                amount += regularization * (1 + onss_rate / 100)
        return amount

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        year = self.declaration_id.year
        atn_codes = list(self._get_atn_code_mapping())
        cct90_threshold = self.env['hr.rule.parameter']._get_parameter_from_code(
            'cct90_employee_pp_threshold', date=date(int(year), 1, 1), raise_if_not_found=False) or 0

        # The taxable salary is added up from the amounts it is made of, so that each one is declared
        # in the year it is attached to instead of following the aggregate line.
        date_from, date_to = self._get_declaration_period()
        all_payslips = self.env['hr.payslip'].union(employee_payslips.values())
        base_values = all_payslips._l10n_be_get_gross_wage_base_values(date_from, date_to)

        def taxable(code, payslips):
            return sum(base_values[code][p.id] for p in payslips)

        # Box 26h: the commuting reimbursements of the students, recognized by the category of their salary rules
        exempted_commuting = all_payslips._l10n_be_get_declaration_base('EXEMPTED_COMMUTING', date_from, date_to)
        # Boxes 14c and 14d: the lump sum commute allowances, unless their payslip paid them as expenses of the employer
        # (box 26a), as it did before they were treated as commuting reimbursements: their lump sum allowances line
        # (REP.FEES) then holds more than the rules still categorized as such.
        serious_base = all_payslips._l10n_be_get_declaration_base('SERIOUS_BASE_LUMP_SUM_ALLOWANCE', date_from, date_to)
        commuting_payslips = all_payslips.filtered(
            lambda p: round(all_line_values['REP.FEES'][p.id]['total'] - serious_base[p.id], 2) <= 0)

        # Zone 2036: the French cross-border workers, read on all the payslips at once
        cross_border_employees = all_payslips.filtered(
            lambda p: p.version_id.l10n_be_resident_situation == 'cross_border').employee_id
        employees = self.env['hr.employee'].browse().union(employee_payslips.keys())
        mobility_budget_total_amount_by_employee = employees._get_l10n_be_mobility_budget_amount_prorated(year=year)
        max_other_transport_exemption = self.env['hr.rule.parameter']._get_parameter_from_code(
                'pricate_car_taxable_threshold',
                date=date(int(year), 1, 1))
        other_transport_exemption_by_niss = defaultdict(float)
        overtime_values = self._get_overtime_values(employee_payslips, year)

        for employee, mapped_total in mapped_totals_by_employee.items():
            payslips = employee_payslips[employee]
            # Box 7b: an arrear payslip is declared as a whole in the arrears, whatever its structure, but for the
            # amounts declared in the boxes of their own (non recurring benefits, commuting)
            arrear_payslips = payslips.filtered('l10n_be_arrear_salary')
            regular_payslips = payslips - arrear_payslips
            # Box 6b: the benefits in kind of the arrears are arrears, declared in box 7b with the rest of their payslip
            atn_amounts = {
                code: sum(all_line_values[code][p.id]['total'] for p in regular_payslips) for code in atn_codes
            }

            commute_allowance_payslips = payslips & commuting_payslips
            # The car allowance paid as expenses wasn't part of the taxable salary of its payslip
            expenses_car_allowance = {
                p.id: all_line_values['LSA_CAR_TRAVEL_KM'][p.id]['total'] for p in payslips - commuting_payslips}
            commute_car_allowance = sum(all_line_values['LSA_CAR_TRAVEL_KM'][p.id]['total'] for p in commute_allowance_payslips)
            # Box 14c: the private car reimbursement and the lump sum car commute allowance
            private_transport_reimbursement = max(0, mapped_total['CAR.PRIV'] + commute_car_allowance)
            # Box 14c: the company car benefit up to the yearly limit, whatever the other commuting reimbursements
            # ("avis aux débiteurs", annex 6: the lowest of the benefit and the limit), shared by the forms of a person
            remaining_exemption = max_other_transport_exemption - other_transport_exemption_by_niss[employee.niss]
            company_car_exemption = max(0, min(atn_amounts['ATN.CAR'] + atn_amounts['ATNCARREGUL'], remaining_exemption))
            other_transport_mean = private_transport_reimbursement + company_car_exemption
            other_transport_exemption_by_niss[employee.niss] += company_car_exemption
            # Box 9: the non recurring benefits up to the yearly limit, the excess is declared in box 6a, or in box 7b
            # for the arrears. The taxable salary of the bonus payslip is the excess left by the exemption applied on
            # that payslip. The limit is shared proportionally between the benefits of the year (box 9a) and the
            # arrears (box 9b).
            cct90_payslips = regular_payslips.filtered(lambda p: p.struct_id.code == 'BECCT90')
            cct90_arrear_payslips = arrear_payslips.filtered(lambda p: p.struct_id.code == 'BECCT90')
            cct90_payslip_exemption = -sum(all_line_values['PP_EXEMP'][p.id]['total'] for p in cct90_payslips)
            cct90_arrear_payslip_exemption = -sum(all_line_values['PP_EXEMP'][p.id]['total'] for p in cct90_arrear_payslips)
            cct90_bonus = max(0, taxable('BONUS_GROSS', cct90_payslips) + cct90_payslip_exemption)
            cct90_arrear_bonus = max(0, taxable('BONUS_GROSS', cct90_arrear_payslips) + cct90_arrear_payslip_exemption)
            cct90_exempted, cct90_arrear_exempted = cct90_bonus, cct90_arrear_bonus
            if cct90_bonus + cct90_arrear_bonus > cct90_threshold:
                cct90_exempted = cct90_threshold * cct90_bonus / (cct90_bonus + cct90_arrear_bonus)
                cct90_arrear_exempted = cct90_threshold * cct90_arrear_bonus / (cct90_bonus + cct90_arrear_bonus)
            termination_payslips = regular_payslips.filtered(lambda p: p.struct_id.code == 'BETERM')
            holiday_gross = taxable('HOLIDAY_TERM_GROSS', regular_payslips.filtered(lambda p: p.struct_id.code == 'BEHOLN'))
            horeca_occasional_pay = mapped_total['HORECA_OCC_TAXABLE']
            horeca_occasional_holiday_pay = 0.0
            if round(horeca_occasional_pay, 2) > 0 and holiday_gross:
                monthly_pay = taxable('GROSS', regular_payslips.filtered(lambda p: p.struct_id.code == 'BEMONTHLY'))
                horeca_occasional_holiday_pay = holiday_gross * horeca_occasional_pay / (horeca_occasional_pay + max(monthly_pay, 0))
            # Box 19: the voluntary overtime of the recovery plan is declared with the year it was worked in
            relance_amount = defaultdict(float)
            relance_hours = defaultdict(float)
            for p in payslips:
                relance_amount[p.date_from.year] += all_line_values['VOLOTNOONSS'][p.id]['total']
            for wd in payslips._l10n_be_get_attached_worked_days(date_from, date_to).filtered(lambda wd: wd.code == '039.23'):
                relance_hours[wd.payslip_id.date_from.year] += wd.number_of_hours
            student_payslips = payslips.filtered(lambda p: p.version_id.is_student())
            mapped_total.update({
                'mobility_budget': mobility_budget_total_amount_by_employee.get(employee.id, 0),
                'cross_border': employee in cross_border_employees,
                'total_gross': sum(taxable(code, payslips) for code in base_values) - sum(expenses_car_allowance.values()),
                'warrant_gross': taxable('WARRANT_GROSS', regular_payslips.filtered(lambda p: p.struct_id.code == 'BEWARRANT')),
                # Box 7a: only the holiday pay for the services of the year itself is early holiday pay. The holiday
                # pay of the previous year, paid on departure, is ordinary holiday pay declared in box 6a. The part
                # of the holiday pay of a Horeca occasional worker for the days taxed at the flat rate goes to box
                # 10a with their pay, prorata their pay (social secretariat, RMEXT).
                'holiday_gross': holiday_gross - horeca_occasional_holiday_pay,
                'horeca_occasional_holiday_pay': horeca_occasional_holiday_pay,
                # Box 7c: the regularization of the simple holiday pay recovered from the previous employer is
                # ordinary holiday pay, declared in box 6a even when paid with the termination fees
                'termination_gross': taxable('TERM_GROSS', termination_payslips) - self._get_holiday_pay_regularization(
                    termination_payslips, all_line_values),
                'cct90_payslip_exemption': cct90_payslip_exemption + cct90_arrear_payslip_exemption,
                'cct90_exempted': cct90_exempted,
                'cct90_arrear_exempted': cct90_arrear_exempted,
                # Benefits in kind are declared in 6b, at their gross amount (ONSS included), the ONSS stays deducted from 6a
                'atn_amounts': atn_amounts,
                'atn_total': sum(atn_amounts.values()),
                'private_transport_reimbursement': private_transport_reimbursement,
                # Box 14d: the lump sum bike commute allowance, its exempt part, and its kilometers
                'commute_bike_allowance': sum(
                    all_line_values['LSA_BIKE_TRAVEL_KM'][p.id]['total'] for p in commute_allowance_payslips),
                'commute_bike_kilometers': sum(
                    all_line_values['LSA_BIKE_TRAVEL_KM'][p.id]['quantity'] for p in commute_allowance_payslips
                    if all_line_values['LSA_BIKE_TRAVEL_KM'][p.id]['total']),
                # Box 7b: the arrears with their benefits in kind and the excess of their non recurring benefits, the
                # private car reimbursement of the arrears is declared in box 14 with the other ones
                'arrear_gross': sum(taxable(code, arrear_payslips) for code in base_values)
                    - sum(expenses_car_allowance.get(p.id, 0) for p in arrear_payslips)
                    + cct90_arrear_payslip_exemption - cct90_arrear_exempted
                    - sum(all_line_values['CAR.PRIV'][p.id]['total'] for p in arrear_payslips)
                    - sum(all_line_values['LSA_CAR_TRAVEL_KM'][p.id]['total'] for p in arrear_payslips & commuting_payslips),
                # Box 20 / 26d: the flexi-job remuneration taken out of the taxable salary by the exemption, the
                # part of the legal pensioners (no cap) apart, by payslip as the status is the one at the work date
                'flexi_exemption': -mapped_total['FLEXI_EXEMPTION'],
                'flexi_exemption_pensioner': -sum(
                    all_line_values['FLEXI_EXEMPTION'][p.id]['total'] for p in payslips if p.version_id.l10n_be_is_retired),
                # Box 26h: the remuneration of the student contracts, already included in the other boxes, taxable
                # or not: the bonuses with their exempt part and the commuting reimbursements are included, the
                # private car one is part of the taxable salary
                'student_remuneration': sum(taxable(code, student_payslips) for code in base_values) - sum(
                    all_line_values['PP_EXEMP'][p.id]['total'] for p in student_payslips) + sum(
                    exempted_commuting[p.id] for p in student_payslips),
                'relance_amount': relance_amount,
                'relance_hours': relance_hours,
                **overtime_values[employee],
                # Box 17: within the limit of 360 hours with a registered cash system, of 300 hours without one
                **self._get_horeca_overtime_values(payslips),
                'other_transport_mean': other_transport_mean,
                'company_car_exemption': company_car_exemption,
            })
            # Box 6a: the remuneration, without the amounts declared in the other boxes. The ONSS on the benefits in
            # kind stays deducted from it. Without a remuneration to deduct it from (benefits in kind kept during an
            # unpaid leave), it is deducted from the benefits in kind of box 6b instead: Belcotax refuses a negative
            # amount.
            # The presence tokens of an employee (not flagged for the 281.30) are out of the withholding tax base but
            # part of its remuneration
            ordinary_remuneration = mapped_total['total_gross'] + mapped_total['PRESENCE_TOKEN'] \
                + mapped_total['cct90_payslip_exemption'] \
                - mapped_total['cct90_exempted'] - mapped_total['cct90_arrear_exempted'] - mapped_total['termination_gross'] \
                - mapped_total['arrear_gross'] - mapped_total['warrant_gross'] \
                - mapped_total['holiday_gross'] - mapped_total['horeca_occasional_holiday_pay'] \
                - mapped_total['atn_total'] - private_transport_reimbursement \
                + mapped_total['horeca_overtime_excess']
            benefits_in_kind = max(mapped_total['atn_total'] - company_car_exemption, 0)
            # What can't be deducted from the benefits in kind either is lost, with a warning on the declaration.
            ordinary_remuneration, benefits_in_kind, lost_remuneration = self._deduct_negative_remuneration(
                ordinary_remuneration, benefits_in_kind)
            mapped_total.update({
                'ordinary_remuneration': ordinary_remuneration,
                'benefits_in_kind': benefits_in_kind,
                'lost_remuneration': lost_remuneration,
                # any remuneration, taxable or not, to declare on the 281.10
                'has_remuneration': any(round(amount, 2) for amount in (
                    mapped_total['total_gross'], mapped_total['PRESENCE_TOKEN'],
                    mapped_total['cct90_payslip_exemption'], mapped_total['flexi_exemption'],
                    mapped_total['mobility_budget'], mapped_total['horeca_overtime_excess'],
                    sum(exempted_commuting[p.id] for p in payslips),
                    *(mapped_total[key] for key in mapped_total if key.startswith('horeca_overtime_') and 'hours' not in key),
                )),
            })
        return mapped_totals_by_employee

    def _check_employee_values(self, sheet_values, evaluation_plan, line_values):
        warnings = []
        currency = self.declaration_id.company_id.currency_id
        lost_remuneration = line_values.get('lost_remuneration', 0)
        if currency.round(lost_remuneration) > 0:
            warnings.append(self.env._(
                "the remuneration of box 6a is negative, %(amount)s are not declared (Belcotax refuses a negative "
                "amount). Check the payslips of the year, the negative amount may have to be declared with the "
                "arrears, the termination fees or the early holiday pay.",
                amount=format_amount(self.env, lost_remuneration, currency),
            ))
        # "Avis aux débiteurs", annex 2: with a mobility budget, the public transport reimbursement is a benefit in
        # kind (box 6b) and the bike reimbursement goes to box 14c, but for exceptions Odoo doesn't know
        commuting = sum(line_values.get(code, 0) for code in ('PUB.TRANS', 'TRAIN', 'CYCLE'))
        if round(line_values.get('mobility_budget', 0), 2) and currency.round(commuting) > 0:
            warnings.append(self.env._(
                "a mobility budget and commuting reimbursements (%(amount)s, boxes 14a and 14d) the same year. Unless "
                "an exception applies (company car during the 3 months before the request of the mobility budget), "
                "the public transport reimbursement is a benefit in kind (box 6b) and the bike reimbursement goes to "
                "box 14c: correct the form if needed.",
                amount=format_amount(self.env, commuting, currency),
            ))
        return warnings

    def _get_declaration_warnings(self):
        # The employees without remuneration get no form when their contributions are transferred to their 281.18,
        # or a form holding only them: no employee is left out for his negative amounts
        return self._get_employee_values_warnings(self.env['hr.payslip'])

    def _get_atn_code_mapping(self):
        return {
            'ATN_HOUSING_FISCAL': 'B',
            'ATN_HEATING': 'C',
            'ATN_ELEC': 'D',
            'ATN.CAR': 'F',
            'ATNCARREGUL': 'F',
            'ATN.LAP': 'H',
            'ATN.INT': 'I',
            'ATN.TAB': 'J',
            'ATN.PHONE_AMT': 'J',
            'ATN.MOB': 'K',
            'ATN_RENT': 'Z',
            'ATN_PENSION': 'Z',
            'ATN_SOCIAL_CONTRIB': 'Z',
            'ATN_MISC': 'Z',
            'ATN_MISC_NO_ONSS': 'Z',
            'TRAFFIC_FINES': 'Z',
            'TRAFFIC_FINES_LIGHT': 'Z',
            'FUEL_CARD_PRIV': 'Z',
            # the taxable gift vouchers are benefits obtained otherwise than in cash
            'GIFT_VOUCHER_ONSS_PP': 'Z',
            'GIFT_VOUCHER_NO_ONSS': 'Z',
        }

    def _post_process_rendering_data_pdf(self, rendering_data):
        for sheet_values in rendering_data['employees_data']:
            for key, value in sheet_values.items():
                if key == "f10_2090_outborderdays":
                    sheet_values[key] = self.env._("%s days", value)
                elif key == "f10_2226_kmzone2207":
                    sheet_values[key] = self.env._("%s km", value)
                elif key in HOURS_TAGS:
                    sheet_values[key] = self.env._("%s hours", f'{value:,.2f}')
        return super()._post_process_rendering_data_pdf(rendering_data)
