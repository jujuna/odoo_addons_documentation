# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class L10n_Be281_20(models.Model):
    _name = 'l10n_be.281_20'
    _inherit = ['l10n_be.281.mixin']
    _description = 'HR Payroll 281.20 Wizard'

    def _get_declaration_code(self):
        return '281.20'

    def _get_withholding_tag(self):
        return 'f20_2066_totaalbedrijfsvoorheffing'

    def _get_eligible_employees(self, payslips):
        return payslips._l10n_be_filter_remuneration_form('281.20').employee_id

    def _get_precomputed_employee_data(self, employee_payslips, all_line_values, mapped_totals_by_employee):
        # Box 19 b): the mobility budget the director was entitled to during the year, prorated to the days of
        # participation (circular 2024/C/16 n° 61-62)
        employees = self.env['hr.employee'].union(mapped_totals_by_employee)
        mobility_budgets = employees._get_l10n_be_mobility_budget_amount_prorated(year=self.declaration_id.year)

        # Box 6: as on the 281.10 and the 274.20, the taxable salary is added up from the amounts it is made of, so
        # that each one is declared in the year it is attached to instead of following the aggregate line.
        date_from, date_to = self._get_declaration_period()
        all_payslips = self.env['hr.payslip'].union(employee_payslips[employee] for employee in mapped_totals_by_employee)
        base_values = all_payslips._l10n_be_get_gross_wage_base_values(date_from, date_to)
        # The benefits in kind and the rent are part of the taxable salary, they are declared in 2068 and 2073
        atn_codes = list(self._get_atn_code_mapping()) + ['ATN_RENT']
        cct90_threshold = self.env['hr.rule.parameter']._get_parameter_from_code(
            'cct90_employee_pp_threshold', date=date_from, raise_if_not_found=False) or 0

        for employee, mapped_total in mapped_totals_by_employee.items():
            payslips = employee_payslips[employee]

            def taxable(code, payslips=payslips):
                code_values = base_values.get(code, {})
                return sum(code_values.get(payslip.id, 0.0) for payslip in payslips)

            # The taxable part of the bike allowance (above the exempted amount per kilometer) is declared in
            # box 6b, "Autres rémunérations" (avis aux débiteurs 281.20)
            taxable_bike_allowance = mapped_total['CYCLE.TAX']
            # Box 9 (code 418): the non recurring benefits linked to results up to the yearly limit, the excess is
            # declared in box 6b. The taxable salary of the bonus payslip is the excess left by the exemption applied
            # on that payslip, as on the 281.10.
            cct90_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BECCT90')
            cct90_payslip_exemption = -sum(all_line_values['PP_EXEMP'][p.id]['total'] for p in cct90_payslips)
            cct90_bonus = taxable('BONUS_GROSS', cct90_payslips) + cct90_payslip_exemption
            cct90_exempted = max(0, min(cct90_bonus, cct90_threshold))
            # Box 6a: the periodic remuneration, the holiday pays included (double holiday pay, holiday pay of the
            # previous year paid at departure: avis aux debiteurs 281.20, "pecules de vacances")
            early_holiday_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BEHOLN')
            holiday_pay = taxable('DH_GROSS') + taxable('HOLIDAY_TERM_GROSS', payslips - early_holiday_payslips)
            periodic_remuneration = taxable('GROSS') - sum(mapped_total[code] for code in atn_codes) \
                - taxable_bike_allowance + holiday_pay
            # Box 8a (code 402): the early holiday pay, the holiday pay of the year paid at departure, taxable
            # separately
            early_holiday_pay = taxable('HOLIDAY_TERM_GROSS', early_holiday_payslips)
            # Box 6b: the other remunerations, the presence tokens of the director included (out of the
            # withholding tax base), and the bonuses of the bonus payslips other than the non recurring benefits (a
            # year-end or exceptional bonus, a 13th month, avis aux debiteurs 281.20: non periodic remunerations)
            bonus = taxable('BONUS_GROSS', payslips - cct90_payslips)
            other_remuneration = taxable('GROSS_NP') + taxable_bike_allowance + cct90_bonus - cct90_exempted \
                + mapped_total['PRESENCE_TOKEN'] + bonus
            # Belcotax refuses a negative amount: as on the 281.10, a negative box 6a (a year with only a correction)
            # is deducted from box 6b, what is left is set aside and reported by _check_employee_values
            periodic_remuneration, other_remuneration, negative_remuneration = self._deduct_negative_remuneration(
                periodic_remuneration, other_remuneration)

            # Box 17: the remunerations of a director under an employment contract, repeated from the codes 400 and
            # 401 (code 411) and from the code 432 (code 420). Only the payslips of the versions under an employment
            # contract count, the director may have had a mandate without one during the year.
            def warrant(payslips):
                return sum(all_line_values['WARRANT_GROSS'][p.id]['total'] for p in payslips if p.struct_id.code == 'BEWARRANT')

            def line_total(code, payslips):
                return sum(all_line_values[code][p.id]['total'] for p in payslips)

            contract_payslips = payslips.filtered(lambda p: p.version_id._l10n_be_is_director_under_employment_contract())
            # Codes 400 (2063, without its zones that Odoo leaves at 0) and 401 (2075)
            remuneration_400_401 = periodic_remuneration + other_remuneration \
                + sum(mapped_total[code] for code in atn_codes) + warrant(payslips)
            if contract_payslips == payslips:
                contract_remuneration = remuneration_400_401
            elif contract_payslips:
                # The share of the non recurring benefits above the limit follows the bonuses of these payslips
                contract_cct90_bonus = taxable('BONUS_GROSS', contract_payslips & cct90_payslips) \
                    - sum(all_line_values['PP_EXEMP'][p.id]['total'] for p in contract_payslips & cct90_payslips)
                contract_cct90_excess = (cct90_bonus - cct90_exempted) * contract_cct90_bonus / cct90_bonus if cct90_bonus else 0
                contract_remuneration = taxable('GROSS', contract_payslips) + taxable('GROSS_NP', contract_payslips) \
                    + contract_cct90_excess + line_total('PRESENCE_TOKEN', contract_payslips) + warrant(contract_payslips) \
                    + taxable('BONUS_GROSS', contract_payslips - cct90_payslips) + taxable('DH_GROSS', contract_payslips) \
                    + taxable('HOLIDAY_TERM_GROSS', contract_payslips - early_holiday_payslips)
                contract_remuneration = min(max(contract_remuneration, 0), remuneration_400_401)
            else:
                contract_remuneration = 0
            mapped_total.update({
                'mobility_budget': mobility_budgets.get(employee.id, 0),
                'periodic_remuneration': periodic_remuneration,
                'other_remuneration': other_remuneration,
                'early_holiday_pay': early_holiday_pay,
                'negative_remuneration': negative_remuneration,
                'cct90_exempted': cct90_exempted,
                'director_contract_remuneration': contract_remuneration,
                # Box 2 is only filled for a director under an employment contract
                'director_under_employment_contract': bool(contract_payslips),
                # Code 432: the bicycle allowance (2207), Odoo has no company bicycle benefit (2208)
                'director_contract_bicycle': line_total('CYCLE', contract_payslips),
            })
        return mapped_totals_by_employee

    def _check_employee_values(self, sheet_values, evaluation_plan, line_values):
        warnings = []
        if round(line_values.get('negative_remuneration', 0.0), 2):
            warnings.append(self.env._(
                "the remuneration of box 6a is negative, %(amount)s are left once deducted from box 6b: set to 0, "
                "declare the recovered remuneration by hand.",
                amount=f"{-line_values['negative_remuneration']:,.2f}",
            ))
        if reset_zones := self._reset_negative_amounts(sheet_values, evaluation_plan):
            warnings.append(self.env._(
                "the negative amounts of the zones %(zones)s are set to 0: declare the recovered amounts by hand.",
                zones=', '.join(reset_zones),
            ))
        return warnings

    def _get_declaration_warnings(self):
        # A director gets a form whatever his amounts: no employee is left out for his negative amounts
        return self._get_employee_values_warnings(self.env['hr.payslip'])

    def _get_atn_code_mapping(self):
        return {
            'ATNCARREGUL': '',
            'ATN_HOUSING_FISCAL': 'B',
            'ATN_HEATING': 'C',
            'ATN_ELEC': 'D',
            'ATN.CAR': 'F',
            'ATN.LAP': 'H',
            'ATN.INT': 'I',
            'ATN.PHONE_AMT': 'J',
            'ATN.TAB': 'J',
            'ATN.MOB': 'K',
            'ATN_PENSION': 'Z',
            'ATN_SOCIAL_CONTRIB': 'Z',
            'ATN_MISC': 'Z',
            'ATN_MISC_NO_ONSS': 'Z',
            'TRAFFIC_FINES': 'Z',
            'TRAFFIC_FINES_LIGHT': 'Z',
            'FUEL_CARD_PRIV': 'Z',
        }
