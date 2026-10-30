# Part of Odoo. See LICENSE file for full copyright and licensing details.

import random
import string
from ast import literal_eval
from collections import defaultdict
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from odoo.addons.l10n_be_hr_payroll.models.utils import MU_SERVICE_CODES, WAGE_SERVICE_CODES, format_amount, round_eurocent
from odoo.exceptions import UserError, ValidationError
from odoo.tools import BinaryBytes, config, date_utils, float_round

from odoo import _, api, fields, models, modules

# DMFA Worker Codes
HOLIDAYS = 253
SPECIAL_WORK_ACCIDENT = 255
ASBESTOS = 256
FFE = 809
SPECIAL_FFE = 810
FFE_NON_COMMERCIAL = 811
TERMINATION_FEES = 812
WORKER_SUBSISTENCE_PERCENTAGE = 820
WORKER_RETIREMENT_FUND = 825
WORKER_SUBSISTENCE = 826
WORKER_PENSION = 827
EMPLOYEE_SUBSISTENCE_PERCENTAGE = 830
CPAE = 831
EMPLOYEE_RETIREMENT_FUND = 835
EMPLOYEE_SUBSISTENCE = 836
EMPLOYEE_PENSION = 837
SALARY_MODERATION = 855
SALARY_MODERATION_WITHOUT = 857
RISK_GROUPS = 852
SPECIAL_SOCIAL_CONTRIBUTION = 856
TEMPORARY_UNEMPLOYMENT = 859
DIMONA_OMISSION = 863
WIJNINCKX = 867
ECO_VEHICLE = 868
MOBILITY_BUDGET = 869
JOURNALISTS_PENSION = 878
TRAFFIC_FINES = 889
ACTIVATION = 260
ECONOMIC_UNEMPLOYMENT = 800
NON_RECURRENT_BENEFITS = 888
REDUCED_ACTIVATION = 261

FIRST_HIRE_FIELDS = ['first_hire', 'second_hire', 'third_hire', 'fourth_hire', 'fifth_hire', 'sixth_hire']


def get_flemish_training_worked_days(worked_days):
    flemish_training_types = (
        worked_days.env.ref('hr_work_entry.l10n_be_work_entry_type_flemish_training_time_off', raise_if_not_found=False),
        worked_days.env.ref('hr_work_entry.l10n_be_work_entry_type_flemish_training_time_off_with_meal_voucher', raise_if_not_found=False),
    )
    return worked_days.filtered(lambda wd: wd.work_entry_type_id in flemish_training_types)


class DMFANode:
    def __init__(self, env, sequence=1):
        self.env = env
        self.sequence = sequence

    def _get_payslip_lines(self, payslips):
        """ The lines of `payslips`, in the order of their line_ids, from the lines read once for the
        whole declaration (self.declaration_data) """
        lines_by_payslip = self.declaration_data['payslip_lines']
        return self.env['hr.payslip.line'].browse(
            line_id for payslip in payslips for line_id in lines_by_payslip[payslip.id])

    @classmethod
    def init_multi(cls, args_list):
        """
        Create multiple instances, each with a consecutive sequence number
        :param args_list: list of __init__ parameters
        :return: list of instances
        """
        sequence = 1
        instances = []
        for args in args_list:
            instances.append(cls(*args, sequence=sequence))
            sequence += 1
        return instances


class DMFACompanyVehicle(DMFANode):

    def __init__(self, vehicle, eco_vehicles, sequence=1):
        super().__init__(vehicle.env, sequence=sequence)
        self.license_plate = vehicle.license_plate
        # Only an eco-friendly vehicle of a mobility budget (contribution 868)
        self.eco_vehicle = vehicle in eco_vehicles


class DMFACompanyContributions(DMFANode):

    def __init__(self, payslips, code, name, amount, basis=-1, sequence=1):
        super().__init__(payslips.env, sequence=sequence)
        self.code = code
        self.name = name
        self.basis_amount = format_amount(basis) if basis != -1 else -1
        self.amount = format_amount(amount)


class DMFANaturalPerson(DMFANode):
    """
    Represents an employee or a student
    """
    def __init__(self, employee, payslips, quarter_start, quarter_end, onss_importance_code, source='dmfa', natural_person_state=None, declaration_data=None, sequence=1):
        super().__init__(employee.env, sequence=sequence)
        self.employee = employee
        self.payslips = payslips
        self.identification_id = employee.niss
        self.quarter_start = quarter_start
        self.quarter_end = quarter_end
        if source == 'consultation':
            self.worker_records = []
            return
        student_payslips = payslips.filtered(lambda p: p.version_id.is_student())
        regular_payslips = payslips - student_payslips
        # A worker record per worker code (e.g. a blue collar becoming a white collar in the quarter)
        workers_payslips = ([student_payslips] if student_payslips else []) + list(
            regular_payslips.grouped(lambda p: p.version_id.l10n_be_worker_code_id.dmfa_code).values())
        if not workers_payslips:
            raise UserError(self.env._('No valid payslips found for employee %s', employee.name))
        self.worker_records = []
        is_new_state = not natural_person_state
        for sequence, worker_payslips in enumerate(workers_payslips, start=1):
            worker = DMFAWorker(
                worker_payslips, quarter_start, quarter_end, onss_importance_code, natural_person_state,
                is_new_state=is_new_state and bool(natural_person_state), declaration_data=declaration_data, sequence=sequence)
            natural_person_state = worker.state
            self.worker_records.append(worker)
        self.state = self.worker_records[0].state
        self.natural_person_pid = self.state.natural_person_pid
        self.decl_natural_person_pid = self.state.decl_natural_person_pid
        self.version_number = self.state.version_number


class DMFAWorker(DMFANode):
    """
    Represents the employee contracts
    """
    def __init__(self, payslips, quarter_start, quarter_end, onss_importance_code, natural_person_state=None, is_new_state=False, declaration_data=None, sequence=1):
        super().__init__(payslips.env, sequence=sequence)
        self.payslips = payslips
        self.declaration_data = declaration_data
        self.quarter_start = quarter_start
        self.quarter_end = quarter_end
        self.onss_importance_code = onss_importance_code

        self.frontier_worker = 0
        self.activity_with_risk = self.payslips.version_id[0].l10n_be_risk_class

        self.student_payslips = payslips.filtered(lambda p: p.version_id.is_student())
        payslips = payslips - self.student_payslips

        if self.student_payslips:
            self.worker_code = self.student_payslips.version_id[0].l10n_be_worker_code_id.dmfa_code
        else:
            self.worker_code = payslips.version_id[0].l10n_be_worker_code_id.dmfa_code

        self.local_unit_id = -1 # Deprecated since 2014

        if self.student_payslips:
            self.occupations = []
            skip_remun = False
        else:
            self.occupations = self._prepare_occupations(self.payslips.mapped('version_id'), self.quarter_start, self.quarter_end)
            skip_remun = all(o.skip_remun for o in self.occupations)

        self._prepare_occupation_deductions(self.occupations)
        self.activation_information = self._prepare_activation_information()

        current_state_data = {
            'deductions': [],
            'contributions': [],
            'occupations': [],
            'student_contributions': [],
            'update_action': 9,
        }

        self.student_contributions = []
        self.contributions = []
        self.deductions = []
        self.first_hire_reduction = None
        if not skip_remun:
            self.deductions = self._prepare_worker_deductions()
            if self.student_payslips:
                self.student_contributions = self._prepare_student_contributions()
            if payslips:
                self.contributions = self._prepare_contributions()
                self._prepare_first_hires_reductions()
        self._keep_one_target_group_reduction()
        self._cap_target_group_reductions()
        self._declare_elderly_service_exemption_notion()

        for contribution in self.student_contributions:
            student_contribution_dict = {
                'student_remun_amount': contribution.student_remun_amount,
                'student_contribution_amount': contribution.student_contribution_amount,
                'student_nbr_days': contribution.student_nbr_days,
                'student_hours_nbr': contribution.student_hours_nbr,
                'local_unit_id': contribution.local_unit_id,
            }
            current_state_data['student_contributions'].append(student_contribution_dict)
        for deduction in self.deductions:
            deduction_dict = {
                'code': deduction.code,
                'deduction_calculation_basis': deduction.deduction_calculation_basis,
                'deduction_amount': deduction.amount,
                'deduction_right_starting_date': deduction.deduction_right_starting_date,
                'manager_cost_nbr_months': deduction.manager_cost_nbr_months,
                'replace_inss': deduction.replace_inss,
                'applicant_inss': deduction.applicant_inss,
                'certificate_origin': deduction.certificate_origin,
            }
            current_state_data['deductions'].append(deduction_dict)
        for contribution in self.contributions:
            contribution_dict = {
                'worker_code': contribution.worker_code,
                'contribution_type': contribution.contribution_type,
                'amount': contribution.amount,
                'calculation_basis': contribution.calculation_basis,
                'first_hiring_date': contribution.first_hiring_date
            }
            current_state_data['contributions'].append(contribution_dict)
        for occupation in self.occupations:
            occupation_dict = {
                'ActivityCode': occupation.ActivityCode,
                'TenthOrTwelfth': occupation.TenthOrTwelfth,
                'apprenticeship': occupation.apprenticeship,
                'commission': occupation.commission,
                'is_parttime': occupation.is_parttime,
                'days_per_week': occupation.days_per_week,
                'employment_promotion': occupation.employment_promotion,
                'flying_staff_class': occupation.flying_staff_class,
                'days_justification': occupation.days_justification,
                'position_code': occupation.position_code,
                'ref_mean_working_hours': occupation.ref_mean_working_hours,
                'mean_working_hours': occupation.mean_working_hours,
                'worker_status': occupation.worker_status,
                'work_place': occupation.work_place,
                'remun_method': occupation.remun_method,
                'sequence': occupation.sequence,
                'reorganisation_measure': occupation.reorganisation_measure,
                'occupation_informations': occupation.occupation_informations,
                'date_start': occupation.date_start,
                'date_stop': occupation.date_stop,
                'retired': occupation.retired,
                'remunerations': [],
                'occupation_deductions': [],
            }
            if natural_person_state:
                version_map = natural_person_state.occupation_version_map or {}
                occupation_dict['version_number'] = version_map.get(occupation.contract.id, 1)
            else:
                occupation_dict['version_number'] = 1
            for remun in occupation.remunerations:
                occupation_dict['remunerations'].append({
                    'sequence': remun.sequence,
                    'code': remun.code,
                    'frequency': remun.frequency,
                    'amount': remun.amount,
                    'percentage_paid': remun.percentage_paid,
                })
            for deduction in occupation.occupation_deductions:
                occupation_dict['occupation_deductions'].append({
                    'sequence': deduction.sequence,
                    'deduction_code': deduction.deduction_code,
                    'deduction_calculation_basis': deduction.deduction_calculation_basis,
                    'deduction_amount': deduction.deduction_amount,
                    'deduction_right_starting_date': deduction.deduction_right_starting_date,
                    'management_cost_nbr_months': deduction.management_cost_nbr_months,
                    'replaced_inss': deduction.replaced_inss,
                    'applicant_inss': deduction.applicant_inss,
                    'certificate_origin': deduction.certificate_origin,
                })
            current_state_data['occupations'].append(occupation_dict)

        if natural_person_state and is_new_state:
            # Another worker record of the natural person, created with this declaration
            natural_person_state.worker_record_data = {**natural_person_state.worker_record_data, self.worker_code: current_state_data}
        elif natural_person_state:
            natural_person_state.validate_changes(current_state_data, self.worker_code)
        else:
            natural_person_state = self.env['l10n_be.dmfa.natural_person.state'].create({
                'employee_id': self.payslips[0].employee_id.id,
                'niss': self.payslips[0].employee_id.niss,
                'quarter_start': self.quarter_start,
                'quarter_end': self.quarter_end,
                'worker_record_data': {self.worker_code: current_state_data},
            })

        self.state = natural_person_state
        self.version_number = natural_person_state.version_number

    def _prepare_activation_information(self):
        """ Mandatory when an occupation declares a full exemption from work during the quarter (2) or an exemption
        down to less than a third of a full time (7) """
        exempted_versions = self.payslips.version_id.filtered(lambda v: v._should_apply_onss_activation())
        if self.student_payslips or not exempted_versions:
            return None
        payslips = self.payslips.filtered(lambda p: p.version_id in exempted_versions)
        return DMFAActivationInformation(payslips.sorted('date_to')[-1])

    def _prepare_student_contributions(self):
        payslips = self.student_payslips
        basis = round(payslips._get_line_values(['BASIC'], compute_sum=True)['BASIC']['sum']['total'], 2)
        basis *= payslips[0]._l10n_be_get_onss_basis_uplift()
        contributions = [
            DMFAStudentContribution(self.student_payslips, basis)
        ]
        return contributions

    def _prepare_contributions(self):
        # https://www.socialsecurity.be/portail/glossaires/dmfa.nsf/2d585b02976cddabc125686a00590d12/e8361adfc1f6e88cc1256df6002b9948/$FILE/AN2004-1-Fr2.pdf
        contribution_payslips = self.env['hr.payslip']
        for occupation in self.occupations:
            if not occupation.skip_remun:
                contribution_payslips |= occupation.payslips

        # Exclude payslips without remuneration to avoid having a sum of 27€ (ATNs)
        # On a full sick quarter that actually has no presence
        regular_payslips = contribution_payslips.filtered(lambda p: p.struct_id.code == 'BEMONTHLY')
        regular_payslips_no_remun = regular_payslips.filtered(lambda p: not p._get_total_basic_wage_without_double_holiday())
        no_remun = regular_payslips == regular_payslips_no_remun
        if no_remun:
            contribution_payslips -= regular_payslips

        valid_struct_codes = {'BEMONTHLY', 'BETERM', 'BETHIRTEEN', 'BEHOLN', 'BEHOLN1', 'BEWARRANT', 'BECCT90'}
        salary_codes = self.env['hr.payslip']._get_salary_wage_line_codes() - {'DH_SALARY'}
        contribution_payslips = contribution_payslips.filtered(lambda p: p.struct_id.code in valid_struct_codes)
        line_values = contribution_payslips._get_line_values(salary_codes)
        payslip_bases = {}
        for p in contribution_payslips:
            payslip_basis = sum(line_values[code][p.id]['total'] for code in salary_codes)
            if p.struct_id.code == 'BECCT90':
                # Only the CCT 90 bonus above the ceiling is subject to the ordinary contributions
                payslip_basis = max(0, payslip_basis - p._rule_parameter('cct90_employer_onss_threshold'))
            payslip_bases[p] = payslip_basis
        basis = round(sum(payslip_bases.values()), 2)
        # The activation contribution isn't due on a termination indemnity
        activation_basis = round(sum(b for p, b in payslip_bases.items() if p.struct_id.code != 'BETERM'), 2)
        if contribution_payslips:
            # As on the payslips
            basis *= contribution_payslips[0]._l10n_be_get_onss_basis_uplift()
            activation_basis *= contribution_payslips[0]._l10n_be_get_onss_basis_uplift()
        mobility_payments = self.declaration_data['mobility_payments']
        has_mobility_budget_balance = any(mobility_payments[p.id] for p in contribution_payslips)
        termination_payslips = contribution_payslips.filtered(lambda p: p.struct_id.code == 'BETERM')
        has_termination_fees_contribution = termination_payslips._get_line_values(['ONSSEMPLOYER_812'], compute_sum=True)['ONSSEMPLOYER_812']['sum']['total'] > 0
        has_dimona_omission_contribution = bool(contribution_payslips._get_line_values(['ONSSEMPLOYER_863']))
        has_eco_vehicle_contribution = contribution_payslips._get_line_values(['ONSSEMPLOYER_868'], compute_sum=True)['ONSSEMPLOYER_868']['sum']['total'] > 0
        has_worker_subsistence_contribution = contribution_payslips._get_line_values(['ONSSEMPLOYER_826'], compute_sum=True)['ONSSEMPLOYER_826']['sum']['total'] > 0
        has_worker_pension_contribution = contribution_payslips._get_line_values(['ONSSEMPLOYER_827'], compute_sum=True)['ONSSEMPLOYER_827']['sum']['total'] > 0
        has_employee_subsistence_contribution = contribution_payslips._get_line_values(['ONSSEMPLOYER_836'], compute_sum=True)['ONSSEMPLOYER_836']['sum']['total'] > 0
        has_employee_pension_contribution = contribution_payslips._get_line_values(['ONSSEMPLOYER_837'], compute_sum=True)['ONSSEMPLOYER_837']['sum']['total'] > 0

        if not basis:
            return []

        line_values = contribution_payslips._get_line_values([
            'ONSSEMPLOYER_256',
            'ONSSEMPLOYER_255',
            'ONSSEMPLOYER_809',
            'ONSSEMPLOYER_810',
            'ONSSEMPLOYER_831',
            'ONSSEMPLOYER_859',
            'M.ONSS',
        ], compute_sum=True)

        has_asbestos = line_values['ONSSEMPLOYER_256']['sum']['total'] > 0
        has_work_accident = line_values['ONSSEMPLOYER_255']['sum']['total'] > 0
        has_ffe = line_values['ONSSEMPLOYER_809']['sum']['total'] > 0
        has_special_ffe = line_values['ONSSEMPLOYER_810']['sum']['total'] > 0
        has_cpae = line_values['ONSSEMPLOYER_831']['sum']['total'] > 0
        has_temporary_unemployment = line_values['ONSSEMPLOYER_859']['sum']['total'] > 0
        has_special_social_contribution = line_values['M.ONSS']['sum']['total'] != 0
        # Special unemployment contribution, with or without wage moderation, when computed on the payslips
        has_salary_moderation = contribution_payslips._get_line_values(['ONSSEMPLOYER_855'], compute_sum=True)['ONSSEMPLOYER_855']['sum']['total'] > 0
        has_without_salary_moderation = contribution_payslips._get_line_values(['ONSSEMPLOYER_857'], compute_sum=True)['ONSSEMPLOYER_857']['sum']['total'] > 0
        # Other contributions declared when the payslips compute them
        other_codes = [
            FFE_NON_COMMERCIAL, WORKER_SUBSISTENCE_PERCENTAGE, WORKER_RETIREMENT_FUND, EMPLOYEE_SUBSISTENCE_PERCENTAGE,
            EMPLOYEE_RETIREMENT_FUND, RISK_GROUPS, JOURNALISTS_PENSION, TRAFFIC_FINES,
        ]
        other_values = contribution_payslips._get_line_values([f'ONSSEMPLOYER_{code}' for code in other_codes], compute_sum=True)
        other_contributions = [
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, code)
            for code in other_codes
            if other_values[f'ONSSEMPLOYER_{code}']['sum']['total'] > 0
        ]
        # Activation contribution of the workers exempted from work, reduced with a training
        activation_values = contribution_payslips._get_line_values(['ONSSEMPLOYER_260', 'ONSSEMPLOYER_261'], compute_sum=True)
        activation_contributions = [
            DMFAWorkerContribution(contribution_payslips, activation_basis, self.quarter_start, code)
            for code in (ACTIVATION, REDUCED_ACTIVATION)
            if activation_values[f'ONSSEMPLOYER_{code}']['sum']['total'] > 0
        ]
        # Economic unemployment contribution of the employers out of the construction sector, computed on the payslips
        has_economic_unemployment = contribution_payslips._get_line_values(['ONSSEMPLOYER_800'], compute_sum=True)['ONSSEMPLOYER_800']['sum']['total'] > 0
        # Special contribution on the non-recurrent benefits linked to results (CCT 90)
        has_non_recurrent_benefits = contribution_payslips._get_line_values(['ONSSEMPLOYER_888'], compute_sum=True)['ONSSEMPLOYER_888']['sum']['total'] > 0
        # Quarterly annual holidays contribution of the manual workers
        has_holidays = contribution_payslips._get_line_values(['ONSSEMPLOYER_253'], compute_sum=True)['ONSSEMPLOYER_253']['sum']['total'] > 0
        # Manual workers only have ONSS rates under the contribution type 1.
        contribution_type = '1' if contribution_payslips[0].version_id.is_worker() else '0'

        return ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, ASBESTOS),  # quarters due: see the payslip rule
        ] if has_asbestos else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, SALARY_MODERATION),
        ] if has_salary_moderation else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, SALARY_MODERATION_WITHOUT),
        ] if has_without_salary_moderation else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, MOBILITY_BUDGET),
        ] if has_mobility_budget_balance else []) + ([
            DMFAWorkerContribution(termination_payslips, basis, self.quarter_start, TERMINATION_FEES),
        ] if has_termination_fees_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, WORKER_SUBSISTENCE),
        ] if has_worker_subsistence_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, WORKER_PENSION),
        ] if has_worker_pension_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, EMPLOYEE_SUBSISTENCE),
        ] if has_employee_subsistence_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, EMPLOYEE_PENSION),
        ] if has_employee_pension_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, DIMONA_OMISSION),
        ] if has_dimona_omission_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, SPECIAL_WORK_ACCIDENT),
        ] if has_work_accident else []) + [
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, self.worker_code, contribution_type),
        ] + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, FFE),
        ] if has_ffe else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, SPECIAL_FFE),
        ] if has_special_ffe else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, CPAE),
        ] if has_cpae else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, SPECIAL_SOCIAL_CONTRIBUTION),
        ] if has_special_social_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, TEMPORARY_UNEMPLOYMENT),
        ] if has_temporary_unemployment else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, ECO_VEHICLE),
        ] if has_eco_vehicle_contribution else []) + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, HOLIDAYS),
        ] if has_holidays else []) + other_contributions + activation_contributions + ([
            DMFAWorkerContribution(contribution_payslips, basis, self.quarter_start, ECONOMIC_UNEMPLOYMENT),
        ] if has_economic_unemployment else []) + ([
            DMFAWorkerContribution(contribution_payslips.filtered(lambda p: p.struct_id.code == 'BECCT90'), basis, self.quarter_start, NON_RECURRENT_BENEFITS),
        ] if has_non_recurrent_benefits else [])

    def _prepare_occupations(self, contracts, quarter_start, quarter_end):
        def _split_termination_period(date_from, date_to):
            # Split the period into the part of the quarter of the termination, the part of the following
            # quarters of the same year, then one part per following calendar year
            # _split_termination_period(date(2003, 9, 1), date(2005, 2, 28))
            # Returns:
            # [(datetime.date(2003, 9, 1), datetime.date(2003, 9, 30)),
            #  (datetime.date(2003, 10, 1), datetime.date(2003, 12, 31)),
            #  (datetime.date(2004, 1, 1), datetime.date(2004, 12, 31)),
            #  (datetime.date(2005, 1, 1), datetime.date(2005, 2, 28))]
            # _split_termination_period(date(2021, 3, 25), date(2021, 8, 1))
            # [(datetime.date(2021, 3, 25), datetime.date(2021, 3, 31)),
            #  (datetime.date(2021, 4, 1), datetime.date(2021, 8, 1))]
            periods = []
            ends = [date_utils.get_quarter(date_from)[1], date(date_from.year, 12, 31)]
            while date_from <= date_to:
                end = ends.pop(0) if ends else date(date_from.year, 12, 31)
                if end < date_from:
                    continue
                periods.append((date_from, min(end, date_to)))
                date_from = end + relativedelta(days=1)
            return periods

        regular_occupations = []
        # Group contracts with the same occupation
        # as they should be declared together
        # Put termination fees in it's own occupation
        occupation_data = contracts.employee_id.version_ids.sorted('date_start', reverse=True)._get_occupation_dates()
        termination_occupations = []
        considered_payslips = self.env['hr.payslip']
        inactive_version_payslips = self.payslips.filtered(lambda p: not p.version_id.active)
        active_version_payslips = self.payslips - inactive_version_payslips
        worker_codes = contracts.l10n_be_worker_code_id
        for data in occupation_data:
            occupation_contracts, date_from, date_to = data
            # A worker record only declares the versions of its worker code, another worker code is another
            # worker record (e.g. a blue collar becoming a white collar)
            worker_contracts = occupation_contracts.filtered(lambda v: v.l10n_be_worker_code_id in worker_codes)
            if not worker_contracts:
                continue
            if worker_contracts != occupation_contracts:
                occupation_contracts = worker_contracts
                date_from = min(worker_contracts.mapped('date_start'))
                date_to = max(worker_contracts.mapped('date_end')) if all(worker_contracts.mapped('date_end')) else False
            payslips = active_version_payslips.filtered(lambda p: p not in considered_payslips and p.version_id in occupation_contracts)
            for slip in inactive_version_payslips:
                if slip not in considered_payslips and slip.date_from <= (date_to or quarter_end) and slip.date_to >= date_from:
                    payslips += slip
            considered_payslips += payslips
            termination_payslips = payslips.filtered(lambda p: p.struct_id.code == 'BETERM')
            if termination_payslips:
                # Le salaire et les données relatives aux prestations se rapportant à une indemnité
                # payée suite à une rupture irrégulière de contrat de travail doivent toujours être
                # repris sur une ligne d'occupation distincte (donc séparée des données se
                # rapportant à la période pendant laquelle le contrat de travail a été exécuté).
                # Les règles de distinction qui étaient d'application sous l'ancienne déclaration
                # pour déclarer des indemnités de rupture sont conservées (la partie se rapportant
                # au trimestre pendant lequel le contrat est rompu, la partie se rapportant aux
                # trimestres ultérieurs de l'année civile en cours, la partie se rapportant à
                # chacune des années civiles suivantes). Les dates de début et de fin de cette
                # ligne d'occupation sont celles des périodes couvertes par l'indemnité de rupture.
                # EXEMPLE:
                # Un employé a été licencié le 31 août 2003 et a droit à une indemnité de rupture
                # de 18 mois. Dans ce cas, vous reprenez les données relatives à la rémunération
                # et aux prestations de ce travailleur sur la déclaration du troisième trimestre de
                # 2003 sur cinq lignes d'occupation différentes.
                # - Ligne 1: les données relatives à la période pendant laquelle il y a eu des
                #            prestations c'est-à-dire du 1er juillet 2003 au 31 août 2003 (tenant
                #            compte naturellement du fait que cette période ne doit pas être scindée
                #            en plusieurs lignes d'occupation).
                # - Ligne 2: les données relatives à l'indemnité de rupture pour la période du 1er
                #            septembre 2003 au 30 septembre 2003.
                # - Ligne 3: les données relatives à l'indemnité de rupture pour la période du 1er
                #            octobre 2003 au 31 décembre 2003.
                # - Ligne 4: les données relatives à l'indemnité de rupture pour la période du 1er
                #            janvier 2004 au 31 décembre 2004.
                # - Ligne 5: les données relatives à l'indemnité de rupture pour la période du 1er
                #            janvier 2005 au 28 février 2005 (fin de la période couverte par
                #            l'indemnité de rupture).
                # A l'exception des cas relativement exceptionnels prévus dans la législation sur
                # les contrats de travail prévoyant que de telles indemnités peuvent être payées
                # mensuellement (entreprises en difficulté), les indemnités doivent toujours être
                # reprises intégralement sur la déclaration du trimestre au cours duquel le contrat
                # de travail a été rompu.
                # YTI Check Termination fees
                # Les indemnités considérées comme de la rémunération sont déclarées
                # en DmfA, avec le code rémunération 3 et en mentionnant, pour la période correspondante
                # couverte par la rémunération, le code prestation 1;
                # <Service>
                #   <ServiceSequenceNbr>1</ServiceSequenceNbr>
                #   <ServiceCode>001</ServiceCode>
                #   <ServiceNbrDays>03900</ServiceNbrDays>
                #   <ServiceNbrHours>29640</ServiceNbrHours>
                # </Service>
                # <Remun>
                #   <RemunSequenceNbr>1</RemunSequenceNbr>
                #   <RemunCode>003</RemunCode>
                #   <RemunAmount>00000400546</RemunAmount>
                # </Remun>
                employee = termination_payslips.employee_id
                # The indemnity covers the period from the day after the last day of the contract
                termination_start = employee.departure_date + relativedelta(days=1)
                termination_periods = _split_termination_period(
                    termination_start, max(employee.l10n_be_notice_period_theoretical_end or termination_start, termination_start))
                termination_values = termination_payslips._get_line_values(['TERM_BASIC'])
                termination_remuneration = sum(termination_values['TERM_BASIC'][p.id]['total'] for p in termination_payslips)
                # values.append((occupation_contracts, termination_payslips, termination_from, termination_to))
                termination_values = [(
                    occupation_contracts,
                    termination_payslips,
                    termination_period[0],
                    termination_period[1],
                    quarter_start,
                    self.declaration_data,
                ) for termination_period in termination_periods]
                termination_sequence = 90
                termination_occupations = DMFAOccupation.init_multi(termination_values)
                calendar = occupation_contracts.sorted(key='date_start', reverse=True)[0].resource_calendar_id
                periods_work_data = [calendar.get_work_duration_data(
                    datetime.combine(period_from, datetime.min.time()),
                    datetime.combine(period_to, datetime.max.time()),
                    compute_leaves=False,
                ) for period_from, period_to in termination_periods]
                # The indemnity is split prorata the periods it covers
                total_hours = sum(work_data['hours'] for work_data in periods_work_data)
                total_days = sum((period_to - period_from).days + 1 for period_from, period_to in termination_periods)
                remaining_remuneration = round(termination_remuneration, 2)
                for index, (termination_occupation, termination_period, occupation_work_data) in enumerate(zip(termination_occupations, termination_periods, periods_work_data)):
                    if index == len(termination_occupations) - 1:
                        period_remuneration = remaining_remuneration
                    elif total_hours:
                        period_remuneration = round(termination_remuneration * occupation_work_data['hours'] / total_hours, 2)
                    else:
                        period_days = (termination_period[1] - termination_period[0]).days + 1
                        period_remuneration = round(termination_remuneration * period_days / total_days, 2)
                    remaining_remuneration = round(remaining_remuneration - period_remuneration, 2)
                    # The end date of a fixed-term contract doesn't end the periods covered by the indemnity
                    termination_occupation.date_start, termination_occupation.date_stop = termination_period
                    termination_occupation.is_termination = True
                    termination_occupation.skip_remun = False
                    termination_occupation.sequence = termination_sequence
                    termination_sequence += 1
                    termination_occupation.services = [DMFANode(termination_payslips.env)]
                    service = termination_occupation.services[0]
                    service.contract = occupation_contracts.sorted(key='date_start', reverse=True)[0]
                    service.code = '001'
                    service.sequence = 99
                    period_days = round(occupation_work_data['days'] * 2) / 2  # Round to half days
                    service.nbr_days = format_amount(period_days, width=5)
                    service.nbr_hours = format_amount(occupation_work_data['hours'], width=5)
                    service.flight_nbr_minutes = -1
                    termination_occupation.remunerations = [DMFANode(termination_payslips.env)]
                    remun = termination_occupation.remunerations[0]
                    remun.code = '003'
                    remun.sequence = 99
                    remun.frequency = -1
                    remun.amount = format_amount(period_remuneration)
                    remun.percentage_paid = -1
            if not termination_payslips and date_to and date_to > quarter_end:
                date_to = False
            regular_occupations.append((occupation_contracts, payslips - termination_payslips, date_from, date_to))

        values = []
        for index, (worked_days, payslip_rates, line_amounts) in self._split_payslips_by_occupation(regular_occupations).items():
            occupation_contracts, _payslips, date_from, date_to = regular_occupations[index]
            values.append((
                occupation_contracts, self.env['hr.payslip'].browse(payslip_rates), date_from, date_to, quarter_start,
                self.declaration_data, worked_days, payslip_rates, line_amounts,
            ))
        return DMFAOccupation.init_multi(values) + termination_occupations

    def _split_payslips_by_occupation(self, occupations):
        """ A payslip can cover several versions (a change in the middle of the month), with worked
        days for each of them. Its worked days are declared on the occupation of their version, and
        its remuneration is split between those occupations, pro rata to the paid amount of their
        worked days: no remuneration on a full suspension (time credit, parental leave).

        :param occupations: [(versions, payslips, date_from, date_to)], each payslip in the
            occupation of its version (or of its dates for an archived version)
        :return: {occupation index: (worked days, {payslip id: share of its remuneration},
            {line id: amount}) for the split payslips}, for the occupations with payslips, in order
        """
        occupation_by_version = {
            version: index for index, (versions, *dummy) in enumerate(occupations) for version in versions}
        worked_days_by_occupation = defaultdict(lambda: self.env['hr.payslip.worked_days'])
        payslip_rates_by_occupation = defaultdict(dict)
        line_amounts_by_occupation = defaultdict(dict)
        for index, (dummy, payslips, *dummy_dates) in enumerate(occupations):
            for payslip in payslips:
                paid_amounts = defaultdict(float)
                for worked_days in payslip.worked_days_line_ids:
                    # Archived versions aren't in the occupations: their worked days stay with the payslip
                    worked_days_index = occupation_by_version.get(worked_days.version_id, index)
                    worked_days_by_occupation[worked_days_index] |= worked_days
                    paid_amounts[worked_days_index] += worked_days.amount if worked_days.is_paid else 0
                total_paid_amount = sum(paid_amounts.values())
                if not total_paid_amount:
                    rates = {index: 1}
                else:
                    rates = {i: amount / total_paid_amount for i, amount in paid_amounts.items()}
                for i in paid_amounts.keys() | rates.keys():
                    payslip_rates_by_occupation[i][payslip.id] = rates.get(i, 0)
                if len(rates) > 1:
                    # Each line rounded to the cent, the rest on the largest share: same total
                    largest = max(rates, key=rates.get)
                    for line in self._get_payslip_lines(payslip):
                        amounts = {i: round_eurocent(line.total * rate) for i, rate in rates.items() if i != largest}
                        amounts[largest] = line.total - sum(amounts.values())
                        for i, amount in amounts.items():
                            line_amounts_by_occupation[i][line.id] = amount
        return {
            index: (worked_days_by_occupation[index], payslip_rates_by_occupation[index], line_amounts_by_occupation[index])
            for index in range(len(occupations)) if payslip_rates_by_occupation[index]
        }

    def _prepare_worker_deductions(self):
        """ Only employment bonus deduction and restructuring deduction are currently supported """
        deduction_code_map = {
            'EmpBonus.1': '0001',
            'ONSSRESTRUCTURING': '0601',
            'ONSSEMPLOYERBASICDEDUC': '1360',
        }
        result = []
        for line_code, dmfa_code in deduction_code_map.items():
            lines = self._get_payslip_lines(self.payslips).filtered(lambda line: line.code == line_code)
            if lines:
                if line_code == 'ONSSRESTRUCTURING' and not any(line.amount > 0 for line in lines):
                    continue
                deduction = DMFAWorkerDeduction(lines, code=dmfa_code)
                if line_code == 'ONSSRESTRUCTURING':
                    # The date of the start of the right is mandatory for the restructuring reduction
                    date_start = self.payslips[:1].employee_id.restructuring_reduction_date_start
                    if date_start:
                        deduction.deduction_right_starting_date = date_start.isoformat()
                elif line_code == 'ONSSEMPLOYERBASICDEDUC':
                    # The calculation basis is mandatory for the wage cap reduction: the remuneration above
                    # the cap, which the reduction is computed on, at the basic and wage moderation rates
                    rates = lines[:1].slip_id._get_onss_global_rates()
                    basic_rate = rates['employer_rate'] + rates['salary_moderation_rate']
                    if basic_rate:
                        deduction.deduction_calculation_basis = format_amount(abs(sum(lines.mapped('total'))) * 100 / basic_rate)
                result.append(deduction)
        return result

    def _get_occupation_deductions(self):
        return [occupation_deduction for occupation in self.occupations for occupation_deduction in occupation.occupation_deductions]

    def _keep_one_target_group_reduction(self):
        """ The structural reduction can be combined with at most one target group reduction on an
        occupation line: keep the highest one """
        for occupation in self.occupations:
            target_groups = [d for d in occupation.occupation_deductions or [] if isinstance(d, DMFAOccupationTargetGroup)]
            if len(target_groups) < 2:
                continue
            best = max(target_groups, key=lambda d: int(d.deduction_amount))
            occupation.occupation_deductions = [d for d in occupation.occupation_deductions if d is best or d not in target_groups]
            if self.first_hire_reduction in target_groups and self.first_hire_reduction is not best:
                self.first_hire_reduction = None

    def _declare_elderly_service_exemption_notion(self):
        """ The service exemption notion is mandatory on the occupations with a Walloon elderly reduction """
        elderly_codes = {int(code) for code in self.env['hr.payslip']._l10n_be_elderly_reduction_codes()}
        for occupation in self.occupations:
            if occupation.contract.l10n_be_working_region != 'wa' or not any(
                    isinstance(d, DMFAOccupationTargetGroup) and d.deduction_code in elderly_codes
                    for d in occupation.occupation_deductions or []):
                continue
            if occupation.occupation_informations:
                occupation.occupation_informations[0].service_exemption_notion = occupation.contract.l10n_be_work_exemption
            else:
                occupation.occupation_informations = DMFAOccupationInformation.init_multi([
                    (occupation.payslips, ['service_exemption_notion'], occupation.quarter_start)])

    def _cap_target_group_reductions(self):
        """ The target group reductions are at most the employer's basic contributions left after the
        structural reduction """
        target_groups = [
            d for occupation in self.occupations for d in occupation.occupation_deductions or []
            if isinstance(d, DMFAOccupationTargetGroup) and int(d.deduction_amount) > 0
        ]
        regular_payslips = self.payslips - self.student_payslips
        if not target_groups or not regular_payslips:
            return
        employer_contributions = 0
        has_rates = False
        for contribution in self.contributions:
            if contribution.worker_code != self.worker_code or contribution.calculation_basis == -1:
                continue
            rates = regular_payslips[0]._get_onss_rates(contribution.worker_code, contribution.contribution_type)
            has_rates = has_rates or bool(rates['total_rate'])
            employer_contributions += int(contribution.calculation_basis) * (rates['total_rate'] - rates['personal_rate']) / 100
        if not has_rates:
            return
        structural_reductions = sum(
            int(d.deduction_amount) for occupation in self.occupations for d in occupation.occupation_deductions or []
            if isinstance(d, DMFAOccupationStructuralDeduction))
        available = max(round(employer_contributions) - structural_reductions, 0)
        for deduction in target_groups:
            amount = min(int(deduction.deduction_amount), available)
            deduction.deduction_amount = format_amount(amount, hundredth=False)
            available -= amount

    def _prepare_first_hires_reductions(self):
        """ The first hires reductions are target group reductions: declared on an occupation line
        (block 90109), with the date of the start of the right, from the flat rate for a full-time
        occupation (G x mu x beta_g), at most the employer contributions left """
        reduction = DMFAFirstHireReduction(
            self.payslips,
            self.quarter_start,
            self.contributions,
            self.deductions,
            self._get_occupation_deductions(),
        )
        if not reduction.code or not reduction.reduction_cap:
            return
        occupations = [o for o in self.occupations if not o.is_termination and o.services]
        if not occupations:
            return
        occupation = max(occupations, key=lambda o: L10n_BeDmfa._get_l10n_be_mu(o.payslips[:1].version_id, services=o.services))
        deduction = DMFAOccupationTargetGroup(
            occupation.payslips, occupation.services, occupation.mean_working_hours, self.mu_global,
            reduction.code, reduction.reduction_cap, p_max=reduction.potential_reduction, starting_date=reduction.starting_date)
        deduction.reduction_cap = reduction.reduction_cap
        if int(deduction.deduction_amount) > 0:
            occupation.occupation_deductions = (occupation.occupation_deductions or []) + [deduction]
            self.first_hire_reduction = deduction

    def _prepare_occupation_deductions(self, occupations):
        mu_global = 0
        for occupation in occupations:
            mu_global += L10n_BeDmfa._get_l10n_be_mu(occupation.payslips[:1].version_id, services=occupation.services)
        self.mu_global = mu_global

        # Structural deduction
        for occupation in occupations:
            if not sum(int(s.nbr_hours) / 100 for s in occupation.services if int(s.code) in WAGE_SERVICE_CODES):
                occupation.occupation_deductions = DMFAOccupationStructuralDeduction.init_multi([])
            else:
                amount = L10n_BeDmfa._get_l10n_be_structural_deduction_3000(occupation.payslips, mu_global=mu_global)
                occupation.occupation_deductions = DMFAOccupationStructuralDeduction.init_multi([(occupation.payslips, amount)])

        # Target-group deductions
        payslip = self.payslips[:1]
        if not payslip:
            return
        employee = payslip.employee_id
        # Quarterly reference wage ss (same definition as the structural reduction).
        ww_quarter = sum(
            int(r.amount) / 100
            for occupation in occupations
            for r in occupation.remunerations
            if int(r.code) in [1, 2, 4, 5, 12]
        )
        hh_quarter = sum(
            int(s.nbr_hours) / 100
            for occupation in occupations
            for s in occupation.services
            if int(s.code) in WAGE_SERVICE_CODES
        )
        uu = payslip.version_id._get_reference_calendar().full_time_required_hours
        ss_quarter = round_eurocent(ww_quarter * round_eurocent(13.0 * uu / hh_quarter)) if hh_quarter else 0
        aggregates = {'mu_global': mu_global, 'ss_quarter': ss_quarter, 'versions': self.payslips.mapped('version_id')}
        for reduction in payslip._l10n_be_target_group_reductions():
            if hasattr(payslip, '_l10n_be_target_group_reduction_%s' % reduction):
                for spec in getattr(payslip, '_l10n_be_target_group_reduction_%s' % reduction)(employee, self.quarter_start, aggregates):
                    for occupation in occupations:
                        occupation.occupation_deductions = (occupation.occupation_deductions or []) + DMFAOccupationTargetGroup.init_multi([(
                            occupation.payslips,
                            occupation.services, occupation.mean_working_hours,
                            mu_global, spec['code'], spec['g'], spec.get('p_max'), spec.get('starting_date'),
                        )])


class DMFAActivationInformation(DMFANode):
    """
    Represents the exemption from work of the activation contribution
    """
    def __init__(self, payslip, sequence=1):
        super().__init__(payslip.env, sequence=sequence)
        version = payslip.version_id
        self.service_exemption_start_date = version.l10n_be_work_exemption_date.isoformat() if version.l10n_be_work_exemption_date else -1
        # At the earliest the start of the exemption
        training_date = max(filter(None, [version.l10n_be_work_exemption_training_date, version.l10n_be_work_exemption_date]), default=None)
        self.training_situation_start_date = training_date.isoformat() if training_date else -1
        self.training_situation = int(version.l10n_be_work_exemption_training_situation)
        _contribution_type, _minimum, increased = payslip._l10n_be_get_activation_contribution_type()
        self.activation_percentage_status = 1 if increased else 0


class DMFAStudentContribution(DMFANode):
    """
    Represents the paid amounts on the student payslips
    """
    def __init__(self, payslips, basis, sequence=None):
        super().__init__(payslips.env, sequence=sequence)
        # The work address of the version of the payslips, not the current one of the employee
        work_address = payslips.version_id[:1].address_id
        location_unit = self.env['hr.work.location'].search([
            ('address_id', '=', work_address.id), ('location_type', '=', 'dmfa_unit')], limit=1)
        self.local_unit_id = format_amount(location_unit._get_code(), width=10, hundredth=False)
        self.student_remun_amount = format_amount(basis, width=9)
        rate = payslips[0]._get_onss_global_rates()['total_rate'] / 100
        self.student_contribution_amount = format_amount(round(basis * rate, 2), width=9)
        self.student_nbr_days = -1
        self.student_hours_nbr = round(payslips._get_worked_days_line_values(['002.00'], ['number_of_hours'], True)['002.00']['sum']['number_of_hours'])


class DMFAWorkerContribution(DMFANode):
    """
    Represents the paid amounts on the employee payslips
    """

    def __init__(self, payslips, basis, quarter_start, worker_code, contribution_type='0', sequence=None):
        super().__init__(payslips.env, sequence=sequence)
        self.worker_code = worker_code
        self.quarter_start = quarter_start

        activation_minimum = 0.0
        if worker_code == FFE:
            contribution_type = payslips[0]._get_ffe_contribution_type()
        elif worker_code == TERMINATION_FEES:
            yearly_salary = payslips[0]._l10n_be_get_termination_yearly_salary()
            contribution_type = payslips[0]._get_termination_fees_contribution_type(yearly_salary)
        elif worker_code == WORKER_SUBSISTENCE:
            contribution_type = 2 if payslips[0].employee_id._get_age() < 25 else 0
        elif worker_code in (WORKER_PENSION, EMPLOYEE_PENSION):
            contribution_type, _ = payslips[0]._get_pension_fund_contribution_type()
        elif worker_code == FFE_NON_COMMERCIAL:
            contribution_type = '0' if payslips[0]._with_salary_moderation() else '2'
        elif worker_code in (WORKER_SUBSISTENCE_PERCENTAGE, EMPLOYEE_SUBSISTENCE_PERCENTAGE):
            contribution_type = '0' if payslips[0].payroll_config_id.onss_importance_code in ['1', '2', '3', '4'] else '5'
        elif worker_code == WORKER_RETIREMENT_FUND:
            contribution_type = payslips[0].payroll_config_id.l10n_be_worker_retirement_fund
        elif worker_code == EMPLOYEE_RETIREMENT_FUND:
            contribution_type = payslips[0].payroll_config_id.l10n_be_employee_retirement_fund
        elif worker_code in (ACTIVATION, REDUCED_ACTIVATION):
            contribution_type, activation_minimum, _increased = payslips[-1]._l10n_be_get_activation_contribution_type()
        elif worker_code == ECONOMIC_UNEMPLOYMENT:
            # The reduced flat rate of the companies in difficulty
            contribution_type = '2' if payslips[0].payroll_config_id.l10n_be_in_difficulty else '0'
        self.contribution_type = contribution_type

        if worker_code == MOBILITY_BUDGET:
            line_values = payslips._get_line_values(['MOBILITY_PAYMENT', 'MOBILITY_PAYMENT_PREV_YEAR'], compute_sum=True)
            basis = line_values['MOBILITY_PAYMENT']['sum']['total'] + line_values['MOBILITY_PAYMENT_PREV_YEAR']['sum']['total']
            basis *= payslips[0]._l10n_be_get_onss_basis_uplift()
        elif worker_code == TRAFFIC_FINES:
            # The contribution is due on the traffic fines paid back by the employer
            basis = -payslips._get_line_values(['TRAFFIC_FINES'], compute_sum=True)['TRAFFIC_FINES']['sum']['total']
        elif worker_code == NON_RECURRENT_BENEFITS:
            # The bonus up to the ceiling, the part above being remuneration
            line_values = payslips._get_line_values(['BONUS_SALARY'])
            basis = round(sum(
                min(line_values['BONUS_SALARY'][p.id]['total'], p._rule_parameter('cct90_employer_onss_threshold'))
                for p in payslips), 2)
        elif worker_code == TERMINATION_FEES:
            line_values = payslips._get_line_values(['TERM_BASIC'], compute_sum=True)
            base_amount = line_values['TERM_BASIC']['sum']['total']
            basis = payslips[0]._get_termination_fees_contribution_basis(base_amount)
        self.calculation_basis = format_amount(basis)

        rates = payslips[0]._get_onss_rates(worker_code, contribution_type)
        employee_worker_code = payslips[0].version_id.l10n_be_worker_code_id.dmfa_code
        if worker_code == MOBILITY_BUDGET:
            rate = rates['personal_rate']
        elif worker_code in [
                employee_worker_code, FFE, SPECIAL_FFE, SALARY_MODERATION, SALARY_MODERATION_WITHOUT, HOLIDAYS,
                FFE_NON_COMMERCIAL, WORKER_SUBSISTENCE_PERCENTAGE, WORKER_RETIREMENT_FUND, EMPLOYEE_SUBSISTENCE_PERCENTAGE,
                EMPLOYEE_RETIREMENT_FUND, RISK_GROUPS, TRAFFIC_FINES, NON_RECURRENT_BENEFITS]:
            rate = rates['total_rate']
        else:
            rate = rates['employer_rate']

        # TODO: change with MLEF's task ?
        if worker_code == SPECIAL_SOCIAL_CONTRIBUTION:
            self.amount = format_amount(round(-payslips._get_line_values(['M.ONSS'], compute_sum=True)['M.ONSS']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == DIMONA_OMISSION:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_863'], compute_sum=True)['ONSSEMPLOYER_863']['sum']['total'], 2))
            self.calculation_basis = format_amount(round(sum(payslip._get_input_line_amount('ONSSEMPLOYER_863') for payslip in payslips), 2))
        elif worker_code == ECO_VEHICLE:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_868'], compute_sum=True)['ONSSEMPLOYER_868']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == WORKER_SUBSISTENCE:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_826'], compute_sum=True)['ONSSEMPLOYER_826']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == WORKER_PENSION:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_827'], compute_sum=True)['ONSSEMPLOYER_827']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == EMPLOYEE_SUBSISTENCE:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_836'], compute_sum=True)['ONSSEMPLOYER_836']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == EMPLOYEE_PENSION:
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_837'], compute_sum=True)['ONSSEMPLOYER_837']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code == ECONOMIC_UNEMPLOYMENT:
            # A flat amount per day of economic unemployment, without calculation basis
            self.amount = format_amount(round(payslips._get_line_values(['ONSSEMPLOYER_800'], compute_sum=True)['ONSSEMPLOYER_800']['sum']['total'], 2))
            self.calculation_basis = -1
        elif worker_code in (ACTIVATION, REDUCED_ACTIVATION):
            # With a quarterly minimum
            self.amount = format_amount(max(activation_minimum, round(basis * rate / 100, 2)))
        else:
            self.amount = format_amount(round(basis * rate / 100, 2))
        self.first_hiring_date = -1
        if worker_code == WORKER_SUBSISTENCE and contribution_type == 2:
            # Mandatory for the reduced flat rate of the young workers: the first hiring by the employer
            versions = payslips[0].employee_id.with_context(active_test=False).version_ids
            first_hiring_date = min(versions.filtered('contract_date_start').mapped('contract_date_start'), default=None)
            if first_hiring_date:
                self.first_hiring_date = first_hiring_date.isoformat()  # also kept in the natural person state (json)


class DMFAOccupation(DMFANode):
    """
    Represents the contract
    """
    def __init__(self, contracts, payslips, date_from, date_to, quarter_start, declaration_data,
                 worked_days=None, payslip_rates=None, line_amounts=None, sequence=1):
        """
        :param worked_days: the worked days of the occupation (default: those of the payslips)
        :param payslip_rates: {payslip id: share of its remuneration on this occupation} (default: 1)
        :param line_amounts: {line id: amount on this occupation} for the payslips split between
            several occupations (default: the line total)
        """
        super().__init__(contracts.env, sequence=sequence)
        self.version_number = 0
        self.declaration_data = declaration_data
        self.worked_days = payslips.worked_days_line_ids if worked_days is None else worked_days
        payslip_rates = payslip_rates or {}
        # The payslips whose remuneration is (partly) declared on this occupation
        self.remunerated_payslips = payslips.filtered(lambda p: payslip_rates.get(p.id, 1))
        self.line_amounts = line_amounts or {}

        contract = contracts.sorted(key='date_start', reverse=True)[0]
        calendar = contract.resource_calendar_id
        self.contract = contract
        self.payslips = payslips
        self.is_termination = False  # Period covered by a termination indemnity

        self.date_start = date_from
        self.date_stop = date_to
        self.quarter_start = quarter_start
        quarter_end = quarter_start + relativedelta(months=3, days=-1)
        if contract.date_end and contract.fixed_term and contract.date_end <= quarter_end:
            self.date_stop = contract.date_end

        # See: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/fill_in_dmfa/dmfa_fillinrules/workerrecord_occupationrecords/occupationrecord.html
        time_credit_type_ids = calendar.attendance_ids.work_entry_type_id.filtered('l10n_be_is_time_credit')
        hours_per_week = contract._get_reference_calendar().hours_per_week
        self.ref_mean_working_hours = ('%.2f' % hours_per_week).replace('.', '').zfill(4)

        # Voir Annexe 44: Réorganisation du temps de travail
        if contract.l10n_be_time_credit and any(t.code in ['147.00', '147.05', '147.07', '147.04', '147.08'] for t in time_credit_type_ids):
            if not contract.resource_calendar_id.hours_per_week:
                self.reorganisation_measure = 3
            else:
                self.reorganisation_measure = 4
        elif contract.l10n_be_time_credit and any(t.code == "122.04" for t in time_credit_type_ids):
            self.reorganisation_measure = 5
        else:
            self.reorganisation_measure = -1
        employment_promotion = -1
        if self.contract.l10n_be_is_starterjob:
            employment_promotion = 10
            if self.contract.disabled:
                employment_promotion = 13
            elif not self.contract.employee_id.niss:
                employment_promotion = 16
        self.employment_promotion = employment_promotion
        self.worker_status = contract.l10n_be_worker_status or -1
        self.retired = '1' if contract.l10n_be_is_retired else '0'
        # Mandatory for an apprentice (worker codes 035 and 439), even without a known contract number
        is_apprentice = contract.l10n_be_worker_code_id.dmfa_code in ('035', '439')
        self.apprenticeship = 1 if contract.l10n_be_apprenticeship_contract_number or is_apprentice else -1
        self.remun_method = 2 if contract.commission_on_target else -1
        self.position_code = -1
        self.flying_staff_class = -1
        self.TenthOrTwelfth = -1
        self.ActivityCode = -1  # Facultative
        self.days_justification = -1 # YTI: Will be useful for payroll based on attendances

        if contract.l10n_be_time_credit and any(t.code == '122.04' for t in time_credit_type_ids):
            days_per_week = 5.0
            mean_working_hours = 38.0
        else:
            # The days a week of the worker's schedule (4 hours a day for 5 days a week is 5 days), the days of a
            # time credit aren't working days
            days_per_week = calendar.days_per_week
            if not days_per_week and calendar.calendar_type != 'fixed':
                reference_calendar = contract.reference_calendar_id or contract.company_id.resource_calendar_id
                days_per_week = calendar._get_days_per_week_for_period(
                    quarter_start, quarter_end, reference_calendar.hours_per_day * 3 / 4)
            mean_working_hours = contract.resource_calendar_id.hours_per_week

        self.days_per_week = format_amount(days_per_week, width=3)
        self.mean_working_hours = ('%.2f' % mean_working_hours).replace('.', '').zfill(4)

        self.is_parttime = 1 if (not calendar.is_fulltime and not contract.l10n_be_time_credit) else 0

        self.commission = contract.l10n_be_joint_committee_id.egov3_code
        self.services, self.skip_remun = self._prepare_services()
        if not mean_working_hours and self.reorganisation_measure != 3 and not any(
                wd.work_entry_type_id.count_as == 'working_time' and wd.number_of_hours > 0
                for wd in self.worked_days):
            # 0 hours per week are only allowed for a complete career interruption (reorganisation
            # measure 3) or for a worker with no services to perform during the period
            self.days_justification = 7
        if not self.skip_remun:
            self.remunerations = self._prepare_remunerations()
        else:
            self.remunerations = []
        self.occupation_informations = self._prepare_occupation_informations()
        # The work address of the occupation in the quarter, not the current one of the employee
        work_address = (self.payslips.version_id or contract).sorted('date_start')[-1].address_id
        location_unit = self.env['hr.work.location'].search([('address_id', '=', work_address.id), ('location_type', '=', 'dmfa_unit')], limit=1)
        if not location_unit:
            raise UserError(_('No DMFA location unit linked to work address %(work_address)s for employee %(employee)s', work_address=work_address.name, employee=contract.employee_id.name))
        self.work_place = format_amount(location_unit._get_code(), width=10, hundredth=False)

    def _prepare_services(self):
        services_by_dmfa_code = defaultdict(lambda: self.env['hr.payslip.worked_days'])
        for wd in self.worked_days:
            # Don't declare out of contract + credit time
            if wd.work_entry_type_id.dmfa_code != '-1' and wd.work_entry_type_id.code not in ['000.00', '147.00', '147.05', '147.07', '147.04', '147.08', '147.13']:
                services_by_dmfa_code[wd.work_entry_type_id.dmfa_code] |= wd
        skip_remun = all(dmfa_code in ['30', '50', '52'] for dmfa_code in services_by_dmfa_code.keys())
        # Do not skip remun if there is some remunerations not linked to worked days (PFA, etc)
        skip_remun = skip_remun and not any(p._get_total_basic_wage_without_double_holiday() and p.struct_id.code in ['BETERM', 'BEHOLN', 'BEHOLN1', 'BETHIRTEEN', 'BEWARRANT'] for p in self.remunerated_payslips)
        return (DMFAService.init_multi([(wds,) for wds in services_by_dmfa_code.values()]), skip_remun)

    def _prepare_remunerations(self):
        salary_rules = self.declaration_data['salary_rules']
        regular_gross = salary_rules['regular_gross']
        commission_gross = salary_rules['commission_gross']
        holiday_pay_regularization_n = salary_rules['holiday_pay_regularization_n']
        rule_atn_corr_1 = salary_rules['atn_corr_1']
        rule_atn_corr_2 = salary_rules['atn_corr_2']
        flexi_bonus = salary_rules['flexi_bonus']
        # ANNEXE 7: Codification des rémunérations
        lines = self._get_payslip_lines(self.remunerated_payslips)
        lines_by_code = defaultdict(lines.browse)
        lines_to_deduct_by_code = defaultdict(lines.browse)
        amount_to_deduct_by_code = defaultdict(float)
        # Exclude payslips without remuneration to avoid having a sum of 27€ (ATNs)
        # On a full sick quarter that actually has no presence
        regular_gross_lines = lines.filtered(lambda l: l.salary_rule_id == regular_gross)
        regular_gross_lines_no_remun = regular_gross_lines.filtered(lambda l: not l.slip_id._get_total_basic_wage_without_double_holiday())
        no_remun = regular_gross_lines == regular_gross_lines_no_remun
        has_working_days = any(
            line.work_entry_type_id.count_as == 'working_time' and line.number_of_hours > 0
            for line in self.payslips.worked_days_line_ids
        )
        for line in lines:
            if no_remun and line.salary_rule_id in (
                    regular_gross,
                    rule_atn_corr_1,
                    rule_atn_corr_2,
            ):
                continue
            if has_working_days and line.salary_rule_id in (
                    rule_atn_corr_1,
                    rule_atn_corr_2,
            ):
                continue
            if line.salary_rule_id == flexi_bonus:
                # Already in the gross salary
                continue
            code = int(line.salary_rule_id.l10n_be_remuneration_code)
            # The pay of a flexi-job (with its flexi holiday pay) is declared under the code 22
            gross_code = 22 if line.slip_id.version_id.is_flexi() else 1
            if code == 1:
                code = gross_code
            if line.salary_rule_id == holiday_pay_regularization_n:
                if line.total < 0:
                    code = 12
                elif line.total > 0:
                    code = 14
            if code:
                if line.salary_rule_id.l10n_be_is_bonus_remuneration:
                    frequency = line.salary_rule_id.l10n_be_remuneration_frequency
                else:
                    frequency = None
                lines_by_code[code, frequency] |= line
                if line.slip_id.struct_id.code == 'BECCT90' and line.code == 'BONUS_SALARY':
                    # A CCT 90 bonus is only remuneration above the ceiling, as on the payslip
                    amount_to_deduct = min(line.total, line.slip_id._rule_parameter('cct90_employer_onss_threshold'))
                    if line.id in self.line_amounts and line.total:
                        amount_to_deduct *= self.line_amounts[line.id] / line.total
                    amount_to_deduct_by_code[code, frequency] += amount_to_deduct
                if line.salary_rule_id == commission_gross:
                    lines_to_deduct_by_code[gross_code, None] += line
        # La valeur zéro pour la remuneration est autorisée uniquement pour le solde du budget
        # mobilité (code rémunération 029).
        return DMFARemuneration.init_multi(sorted([(
            lines, code, frequency, lines_to_deduct_by_code[code, frequency], amount_to_deduct_by_code[code, frequency], self.line_amounts,
        ) for (code, frequency), lines in lines_by_code.items()
            if round(sum(self.line_amounts.get(l.id, l.total) for l in lines) - amount_to_deduct_by_code[code, frequency], 2) or code == 29], key=lambda t: (t[1], t[2] or 0)))

    def _prepare_occupation_informations(self):
        infos_to_declare = []
        mobility_payments = self.declaration_data['mobility_payments']
        has_mobility_budget_balance = any(mobility_payments[p.id] for p in self.remunerated_payslips)
        if has_mobility_budget_balance:
            infos_to_declare.append('mobility_budget')
        # Only for a flexi-job declared as an ordinary worker, its Dimona flexi being refused (late Dimona)
        if any(p.version_id.l10n_be_dimona_category == 'flx' and p.version_id.l10n_be_refused_flexijob for p in self.remunerated_payslips):
            infos_to_declare.append('flexi_notion')
        if any(self.remunerated_payslips.version_id.mapped('l10n_be_is_starterjob')):
            infos_to_declare.append('career_measure')
        if get_flemish_training_worked_days(self.worked_days):
            infos_to_declare.append('flemish_training_hours')
        # Mandatory for a worker exempted from work during the whole quarter
        if self.contract.l10n_be_work_exemption != '0':
            infos_to_declare.append('service_exemption_notion')
        return DMFAOccupationInformation.init_multi([(self.remunerated_payslips, infos_to_declare, self.quarter_start, self.worked_days)] if infos_to_declare else [])


class DMFARemuneration(DMFANode):
    """
    Represents the paid amounts on payslips
    """
    def __init__(self, payslip_lines, code, frequency=None, lines_to_deduct=None, amount_to_deduct=0, line_amounts=None, sequence=1):
        """ :param line_amounts: {line id: amount} for the lines split between several occupations """
        super().__init__(payslip_lines.env, sequence=sequence)
        line_amounts = line_amounts or {}

        def total(line):
            return line_amounts.get(line.id, line.total)

        self.code = str(code).zfill(3)

        if frequency is not None:
            self.frequency = str(frequency).zfill(2)
        else:
            self.frequency = -1

        # IP.EXEMPT removes the ONSS-exempt intellectual property from the ONSS base: it is declared
        # as a positive amount under the remuneration code 47
        amount = sum(
            -total(line) if line.code in ("HolPayRec", "IP.EXEMPT") or (line.code == "HolPayReg" and line.total < 0) else total(line)
            for line in payslip_lines
        )
        self.amount = format_amount(amount)
        if lines_to_deduct:
            amount_to_deduct += sum(total(line) for line in lines_to_deduct)
        if amount_to_deduct:
            self.amount = format_amount(int(self.amount) - int(format_amount(amount_to_deduct)), hundredth=False)
        self.percentage_paid = -1

class DMFAOccupationInformation(DMFANode):
    """
    Represents the paid amounts on payslips
    """
    def __init__(self, payslips, infos_to_declare, quarter_start=None, worked_days=None, sequence=1):
        """ :param worked_days: the worked days of the occupation (default: those of the payslips) """
        super().__init__(payslips.env, sequence=sequence)
        if worked_days is None:
            worked_days = payslips.worked_days_line_ids
        self.display_info = bool(infos_to_declare)
        self.holiday_days_number = -1
        self.six_months_illness_date = -1
        self.maribel = -1
        self.horeca_extra = -1
        self.hour_remun = -1
        self.service_exemption_notion = -1
        if 'service_exemption_notion' in infos_to_declare:
            self.service_exemption_notion = payslips.version_id.sorted('date_version')[-1].l10n_be_work_exemption
        self.hour_remun_thousandth = -1
        self.posted_employee = -1
        self.first_week_guaranteed_salary = -1
        self.illness_gross_remun = -1
        self.psddcl_exemption = -1
        self.suppl_pension_exemption = -1
        self.obligation_control = -1
        self.definitive_nomination_date = -1
        self.maribel_date = -1
        self.psp_contrib_derogation = -1
        self.career_measure = 2 if any(payslips.version_id.mapped('l10n_be_is_starterjob')) else -1
        self.sector_detail = -1
        self.mobility_budget = -1
        if 'mobility_budget' in infos_to_declare:
            mobility_budget_amount = 0
            if any(p.input_line_ids.filtered(lambda l: l.code == 'MOBILITY_PAYMENT') for p in payslips):
                mobility_budget_amount = max(payslips.version_id.mapped('l10n_be_mobility_budget_amount'), default=0)
            if any(p.input_line_ids.filtered(lambda l: l.code == 'MOBILITY_PAYMENT_PREV_YEAR') for p in payslips) and quarter_start:
                # The version carrying the mobility budget may have ended in a previous
                # quarter while the remaining balance is only paid out (and declared) in
                # the current quarter, on a version with new mobility budget or with no mobility budget anymore.
                previous_quarter_end = quarter_start - relativedelta(days=1)
                previous_quarter_start = date_utils.get_quarter(previous_quarter_end)[0]
                employee = payslips[:1].employee_id
                previous_versions = employee.version_ids.filtered(
                    lambda v: v.date_start <= previous_quarter_end and (not v.date_end or v.date_end >= previous_quarter_start)
                )
                mobility_budget_amount = max(previous_versions.mapped('l10n_be_mobility_budget_amount'), default=0)
            self.mobility_budget = format_amount(mobility_budget_amount)
        self.flexi_notion = -1
        if 'flexi_notion' in infos_to_declare:
            self.flexi_notion = "FL"
        self.flemish_training_hours = -1
        if 'flemish_training_hours' in infos_to_declare:
            # Mandatory when an absence is for a Flemish training leave, in hundredths of hours
            flemish_training_hours = sum(get_flemish_training_worked_days(worked_days).mapped('number_of_hours'))
            self.flemish_training_hours = format_amount(flemish_training_hours, width=7)
        self.regional_aid_measure = -1


class DMFAService(DMFANode):
    """
    Represents the worked hours/days
    """
    def __init__(self, worked_days, sequence=1):
        super().__init__(worked_days.env, sequence=sequence)
        if len(list(set(worked_days.mapped('work_entry_type_id.dmfa_code')))) > 1:
            raise ValueError("Cannot mix work of different types.")

        self.contract = worked_days.mapped('version_id').sorted(key='date_start', reverse=True)[0]

        work_entry_type = worked_days[0].work_entry_type_id
        if not work_entry_type.dmfa_code:
            raise UserError(self.env._('The following work entry type does not have a DMFA code set: %s', work_entry_type.name))
        self.code = work_entry_type.dmfa_code.zfill(3)

        total_hours = sum(worked_days.mapped('number_of_hours'))
        total_days = sum(worked_days.mapped('number_of_days'))
        total_days = round(total_days * 2) / 2  # Round to half days
        self.nbr_days = format_amount(total_days, width=5)

        self.nbr_hours = format_amount(total_hours, width=5)

        self.flight_nbr_minutes = -1


class DMFAWorkerDeduction(DMFANode):

    def __init__(self, payslip_lines, code, sequence=1):
        super().__init__(payslip_lines.env, sequence=sequence)
        self.code = code
        self.deduction_calculation_basis = -1
        self.amount = format_amount(abs(sum(payslip_lines.mapped('total'))))
        # Could be required for other deductions: See ANNEXE 4
        self.deduction_right_starting_date = -1
        self.manager_cost_nbr_months = -1
        self.replace_inss = -1
        self.applicant_inss = -1
        self.certificate_origin = -1


class DMFAOccupationStructuralDeduction(DMFANode):
    def __init__(self, payslips, amount, sequence=1):
        super().__init__(payslips.env, sequence=sequence)
        self.deduction_code = 3000
        self.deduction_calculation_basis = -1
        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/structuralreduction_targetgroupreductions/introduction.html
        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/structuralreduction_targetgroupreductions/structuralreduction.html
        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/socialsecuritycontributions/contributions.html#heading-4
        # Rcatégorie 1 = 0,1400 x ( 11.013,62 - S) + 0,4000 x (6.943,32 - S); (catégorie générale)
        self.deduction_amount = format_amount(amount)
        self.deduction_right_starting_date = -1
        self.management_cost_nbr_months = -1
        self.replaced_inss = -1
        self.applicant_inss = -1
        self.certificate_origin = -1


class DMFAOccupationTargetGroup(DMFANode):
    """Target-group reduction.

    Quarterly computation: Pg = G x mu x beta_g, optionally capped at p_max
    per occupation line (e.g. the artists reduction).
    Works for all Target Group Deduction , just pass the deduction code and the G code
    """
    def __init__(self, payslips, services,
                 hours_per_week, mu_global, code, G, p_max=None, starting_date=None, sequence=1):
        super().__init__(payslips.env, sequence=sequence)
        if not payslips:
            return
        self.employee = payslips[:1].employee_id
        self.deduction_code = code
        self.deduction_calculation_basis = -1
        version = payslips[:1].version_id
        mu = L10n_BeDmfa._get_l10n_be_mu(version, services=services)

        uu_hours = version._get_reference_calendar().full_time_required_hours if version else 0
        at_least_half_time = int(hours_per_week) / 100 >= (uu_hours / 2.0)
        # No minimum for the reductions of the artists (4300) and of the subsidised contract employees (ACS)
        at_least_half_time = at_least_half_time or code in (4000, 4001, 4300)
        beta_g = payslips[:1]._l10n_be_reduction_beta_g(mu_global, at_least_half_time)

        p = round_eurocent(G * mu * beta_g)
        if p_max is not None:
            p = min(p, p_max)
        self.deduction_amount = format_amount(p)
        self.deduction_right_starting_date = starting_date if starting_date is not None else -1
        self.management_cost_nbr_months = -1
        self.replaced_inss = -1
        self.applicant_inss = -1
        self.certificate_origin = -1


class DMFAFirstHireReduction(DMFAWorkerDeduction):
    """
    Reductions for first hires
    """

    def __init__(self, payslips, quarter_start, contributions, deductions, occupation_deductions, sequence=1):
        self.employee = payslips.employee_id
        self.quarter_start = quarter_start

        self.env = payslips.env

        dmfa_id = self.env.context.get('dmfa_id')
        self.dmfa_record = self.env['l10n_be.dmfa'].browse(dmfa_id) if dmfa_id else None

        field, quarters_used = self._determine_rank_and_quarters_used()

        reduction_cap = 0.0
        code = 0

        if field is not None and quarters_used is not None:
            current_quarter = quarters_used + 1
            reduction_cap, code = self._calculate_reduction_cap_and_dmfa_code(field, current_quarter)

        self.reduction_cap = reduction_cap
        self.potential_reduction = self._calculate_potential_reduction(contributions, deductions, occupation_deductions)
        self.starting_date = self._get_right_starting_date(field) if field else None

        reduction = self._calculate_capped_reduction(
            reduction_cap,
            contributions,
            deductions,
            occupation_deductions,
        )
        super().__init__(self.env['hr.payslip.line'], code, sequence)
        self.amount = format_amount(reduction)

    def _get_right_starting_date(self, field):
        """ The hire date of the worker who opened the right to the reduction of this rank: the one of
        the first declaration using it, the worker may have been replaced since """
        first_dmfa = self.env['l10n_be.dmfa'].search([
            ('company_id', '=', self.dmfa_record.company_id.id),
            ('state', 'in', ('done', 'paid')),
            (field, '!=', False),
        ], order='year asc, quarter asc', limit=1)
        opener = first_dmfa[field] if first_dmfa and first_dmfa.quarter_start < self.quarter_start else self.employee
        versions = opener.with_context(active_test=False).version_ids.filtered('contract_date_start')
        return min(versions.mapped('contract_date_start')).isoformat() if versions else None

    def _determine_rank_and_quarters_used(self):
        if not self.dmfa_record:
            return None, None

        for field in FIRST_HIRE_FIELDS:
            if self.dmfa_record[field] == self.employee:
                company_id = self.dmfa_record.company_id.id
                dmfa_id = self.dmfa_record.id
                quarters_used = self.env['l10n_be.dmfa'].search_count(domain=[
                    ('company_id', '=', company_id),
                    ('id', '!=', dmfa_id),
                    ('state', '=', 'done'),
                    (field, '!=', False),
                ])
                payroll_config = self.dmfa_record._get_payroll_config()
                quarters_used += payroll_config[f'l10n_be_{field}_reductions_used_outside_odoo']
                return field, quarters_used

        return None, None

    @staticmethod
    def _calculate_potential_reduction(contributions, deductions, occupation_deductions):
        total_contributions_cents = sum(int(c.amount) for c in contributions)
        total_deductions_cents = sum(int(d.amount) for d in deductions)
        total_occupation_deductions_cents = sum(int(d.deduction_amount) for d in occupation_deductions)

        return max((total_contributions_cents - total_deductions_cents - total_occupation_deductions_cents) / 100, 0.0)

    def _calculate_capped_reduction(self, reduction_cap, contributions, deductions, occupation_deductions):
        if reduction_cap <= 0:
            return 0.0

        theoretical_max_reduction = self._calculate_potential_reduction(contributions, deductions, occupation_deductions)

        return min(theoretical_max_reduction, reduction_cap)

    def _calculate_reduction_cap_and_dmfa_code(self, field, current_quarter):
        values = self.dmfa_record._get_applicable_first_hires_rule_parameter_values(field)
        # handle cases where there is no rule param or there is one but the rule
        # is abolished at that time (represented by max_quarter = 0)
        if not values or all(b['max_quarter'] == 0 for b in values):
            return 0.0, 0

        for bracket in values:
            latest_eligible_quarter = bracket['max_quarter']
            if current_quarter <= latest_eligible_quarter:
                return bracket['cap'], bracket['code']

        raise UserError(self.env._("You exceeded the allowed number of quarters for this reduction you assigned to %s", self.employee.name))


class L10n_BeDmfa(models.Model):
    _name = 'l10n_be.dmfa'
    _inherit = ["l10n.be.onss.batch.declaration"]
    _description = 'DMFA'
    _order = "year desc, quarter desc"

    @classmethod
    def _l10n_be_is_declared_in_days(cls, versions, payslips=None):
        """Whether the occupation's working time is declared in days only, so that its reductions count days
        (S = W x 13 x D / J, μ = X / 13 x D): a full-time worker's, unless in time credit, back to work part-time
        after an illness or an accident (122.04), a flexi-jobber, a student or any worker of the Horeca sector, whose
        working time is declared in hours and days. Every version the payslips pay must be such a full-time one, on
        the same number of days a week (a part-time or another regime of the month is an occupation of its own).
        https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/fill_in_dmfa/dmfa_fillinrules/servicedatadeclaration/declarationmethod_workerservices.html
        """
        if not versions or len({version._l10n_be_get_days_per_week() for version in versions}) > 1:
            return False
        for version in versions:
            if version.work_time_rate < 1 or version.l10n_be_time_credit or not version.is_classic_employee():
                return False
            employer_category = version.company_id.current_payroll_config_id.l10n_be_employer_category_id.dmfa_code
            if employer_category in ('017', '317') or (version.l10n_be_joint_committee_id.egov3_code or '').startswith('302'):
                return False
        return not payslips or not any(wd.work_entry_type_id.code == '122.04' for wd in payslips.worked_days_line_ids)

    @classmethod
    def _get_l10n_be_mu(cls, version, services=None, payslips=None):
        """μ = fraction of quarterly prestations, shared by the structural and the
        target-group reductions (the ONSS instructions define a single μ for both):
        prestation codes 1, 2, 3, 4, 5, 12, 16, 17, 20, 38, 72; hours-based when hours
        are declared, days-based otherwise (a full-time occupation is declared in
        days only); U/D = the reference worker's regime.
        https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/structuralreduction_targetgroupreductions/introduction.html
        """
        if not services and not payslips:
            return 0.0

        mu_codes = MU_SERVICE_CODES

        if services:
            qualifying = [s for s in services if int(s.code) in mu_codes and s.sequence != 99]
            zz = sum(int(s.nbr_hours) / 100 for s in qualifying)
            xx = sum(int(s.nbr_days) / 100 for s in qualifying)
        else:  # working with payslips
            payslips = payslips.filtered(lambda p: p.struct_id.code != 'BETERM')
            qualifying = [
                wd for wd in payslips.worked_days_line_ids
                if wd.work_entry_type_id.dmfa_code and int(wd.work_entry_type_id.dmfa_code) in mu_codes
            ]
            zz = sum(wd.number_of_hours for wd in qualifying)
            xx = sum(wd.number_of_days for wd in qualifying)

        uu = version._get_reference_calendar().full_time_required_hours if version else 0
        versions = (payslips.worked_days_line_ids.version_id | version) if payslips else version
        if zz > 0 and not cls._l10n_be_is_declared_in_days(versions, payslips):
            return float_round(zz / (13 * uu), 2, rounding_method="HALF-UP") if uu else 0.0
        dd = version._l10n_be_get_days_per_week() if version else 5
        return float_round(xx / (13 * dd), 2, rounding_method="HALF-UP") if dd else 0.0

    @classmethod
    def _get_l10n_be_structural_deduction_3000(cls, payslips, mu_global, result_rules=None):
        payslips = payslips.filtered(lambda p: p.struct_id.code != 'BETERM')

        if not payslips:
            return 0.0

        # U is read as _get_l10n_be_mu reads it: the versions of one occupation can have several reference calendars
        # (e.g. two full-time schedules on other weekdays, each its own reference)
        uu = payslips[:1].version_id._get_reference_calendar().full_time_required_hours

        def _remun_code_and_amount(code, total, rule):
            if code == 'HolPayRec':
                return 12, -total
            elif code == 'HolPayReg':
                if total < 0:
                    return 12, -total
                elif total > 0:
                    return 14, total
            return int(rule.l10n_be_remuneration_code or 0), total

        computing_payslip = payslips.filtered(lambda p: p.id == payslips.env.context.get('current_payslip_id'))
        other_slips = payslips - computing_payslip

        line_data = [_remun_code_and_amount(line.code, line.total, line.salary_rule_id) for line in other_slips.line_ids]
        commission_rule = "COMMISSION"
        commission_deduction = sum(line.total for line in other_slips.line_ids if line.salary_rule_id.code == commission_rule)

        if computing_payslip:
            result_rules = result_rules or {}
            remun_rules = computing_payslip.struct_id.rule_ids.filtered(
                lambda r: int(r.l10n_be_remuneration_code or 0) in {1, 2, 4, 5, 12}
            )

            for rule in remun_rules:
                entry = result_rules.get(rule.code)
                if entry is None:
                    continue
                amount = entry['total'] if isinstance(entry, dict) else entry
                line_data.append(_remun_code_and_amount(rule.code, amount, rule))

            entry = result_rules.get(commission_rule)
            if entry is not None:
                commission_deduction += entry['total'] if isinstance(entry, dict) else entry

        ww = float_round(
            sum(amt for code, amt in line_data if code in {1, 2, 4, 5, 12}) - commission_deduction,
            2
        )

        hh = float_round(sum(
            wd.number_of_hours for wd in payslips.worked_days_line_ids
            if wd.work_entry_type_id.dmfa_code and int(wd.work_entry_type_id.dmfa_code) in WAGE_SERVICE_CODES
        ), 2)

        if not hh:
            return 0.0

        ss = float_round(ww * float_round(13.0 * uu / hh, 2), 2)
        zz = float_round(sum(
            wd.number_of_hours for wd in payslips.worked_days_line_ids
            if wd.work_entry_type_id.dmfa_code and int(wd.work_entry_type_id.dmfa_code) in MU_SERVICE_CODES
        ), 2)
        mu = float_round(zz / (13 * uu), 2) if uu else 0.0
        version = payslips[:1].version_id
        if cls._l10n_be_is_declared_in_days(payslips.worked_days_line_ids.version_id | version, payslips):
            # a full-time occupation is declared in days only: S = W x 13 x D / J, μ = X / (13 x D), whatever the hours
            # of its days (a 40-hour week, a shorter day, overtime hours)
            dd = version._l10n_be_get_days_per_week()
            # extra hours are no days of their own: worked on a day already counted
            day_lines = payslips.worked_days_line_ids.filtered(
                lambda wd: wd.work_entry_type_id.dmfa_code and not wd.work_entry_type_id.is_extra_hours)
            jj = sum(wd.number_of_days for wd in day_lines if int(wd.work_entry_type_id.dmfa_code) in WAGE_SERVICE_CODES)
            xx = sum(wd.number_of_days for wd in day_lines if int(wd.work_entry_type_id.dmfa_code) in MU_SERVICE_CODES)
            if jj and dd:
                ss = float_round(ww * float_round(13.0 * dd / jj, 2), 2)
                mu = float_round(xx / (13 * dd), 2)

        quarter_start = date_utils.get_quarter(payslips[0].date_to)[0]
        RuleParam = payslips.env['hr.rule.parameter'].sudo()
        alpha = RuleParam._get_parameter_from_code('cp200_occupation_deduction_3000_alpha', date=quarter_start, raise_if_not_found=False)
        s0 = RuleParam._get_parameter_from_code('cp200_occupation_deduction_3000_s0', date=quarter_start, raise_if_not_found=False)
        gamma = RuleParam._get_parameter_from_code('cp200_occupation_deduction_3000_gamma', date=quarter_start, raise_if_not_found=False)
        s2 = RuleParam._get_parameter_from_code('cp200_occupation_deduction_3000_s2', date=quarter_start, raise_if_not_found=False)

        if not all(param is not None for param in [alpha, s0, gamma, s2]):
            return 0.0

        rr = (
            float_round(alpha * max(s0 - ss, 0), 2) +
            float_round(gamma * max(s2 - ss, 0), 2)
        )

        # No reduction below 27.5% of a full time, except for a worker at least half-time (average weekly hours of the
        # worker at least half the ones of the reference worker)
        version = payslips[:1].version_id
        at_least_half_time = (version.resource_calendar_id.hours_per_week or 0.0) >= uu / 2
        # The artists and the subsidised contract employees (ACS) have no minimum
        if mu_global < 0.275 and not at_least_half_time and not version._l10n_be_has_no_minimum_occupation():
            beta = 0.0
        elif mu_global < 0.55:
            beta = 1.18
        elif mu_global < 0.8:
            beta = 1.18 + (mu_global - 0.55) * 0.28
        else:
            beta = 1.0 / mu_global

        p = float_round(rr * mu * beta, 2)
        # at most the employer's basic contributions: rates of the contribution type of the worker (blue collars: 1,
        # without rates of type 0) on the base of the contributions (108% for blue collars)
        rates = payslips[0]._get_onss_global_rates()
        p_max = payslips[0]._get_onss_contribution_amount(ww, rates['total_rate'] - rates['personal_rate'])
        return min(p, p_max)

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "BE":
            raise UserError(self.env._('You must be logged in a Belgian company to use this feature'))
        return super().default_get(fields)

    def _get_default_company_id(self):
        company = self.env.company
        if company.parent_id:
            raise UserError(self.env._('DMFA can only be generated from a top-level company.'))
        return company

    def _get_declaration_type(self):
        match self.declaration_type:
            case 'modification':
                return 'DMWA'
            case 'consultation':
                return 'DMRQ'
            case _:
                return 'DMFA'

    def _get_base_schema_url(self):
        base_schema_urls = {
            "original": "https://www.socialsecurity.be/docu_xml/dmfa/",
            "modification": "https://www.socialsecurity.be/docu_xml/dmfaupdate/",
            "consultation": "https://www.socialsecurity.be/docu_xml/dmfarequest/",
        }
        return base_schema_urls[self.declaration_type]

    def _get_base_schema_filename(self):
        base_schema_filenames = {
            "original": "DmfAOriginal_",
            "modification": "DmfAUpdate_",
            "consultation": "DmfAConsultationRequest_",
        }
        return base_schema_filenames[self.declaration_type]

    def _get_declaration_template_xmlid(self):
        match self.declaration_type:
            case 'modification':
                return 'l10n_be_hr_payroll.dmfa_modification_xml_report'
            case 'consultation':
                return 'l10n_be_hr_payroll.dmfa_consultation_xml_report'
            case _:
                return 'l10n_be_hr_payroll.dmfa_xml_report'

    company_id = fields.Many2one('res.company', default=_get_default_company_id, required=True)
    branch_ids = fields.One2many('res.company', compute='_compute_branch_ids', compute_sudo=True)
    onss_declaration_count = fields.Integer(compute='_compute_onss_declaration_count')
    year = fields.Char(required=True, default=lambda self: fields.Date.context_today(self).year)
    company_pid = fields.Char(string="Company PID", help="EmployerDeclarationPID returned by ONSS", required=False)
    quarter = fields.Selection([
        ('1', '1st'),
        ('2', '2nd'),
        ('3', '3rd'),
        ('4', '4th'),
    ], required=True, default=lambda self: str(date_utils.get_quarter_number(fields.Date.context_today(self))))
    declaration_method = fields.Selection([
        ('web', 'Web'),
        ('batch', 'Batch'),
    ], string='Declaration Method', default='web', required=True)
    dmfa_pdf = fields.Binary(string="PDF file")
    dmfa_pdf_filename = fields.Char(compute='_compute_pdf_filename', store=True)
    quarter_start = fields.Date(compute='_compute_dates', store=True)
    quarter_end = fields.Date(compute='_compute_dates', store=True)
    vehicle_ids = fields.One2many('fleet.vehicle', compute='_compute_vehicle_ids')
    payslip_ids = fields.One2many('hr.payslip', 'l10n_be_dmfa_id', compute='_compute_eligible_payslip_ids', string='Reported Payslips', store=True)
    payslip_count = fields.Integer(compute='_compute_payslip_count')
    state = fields.Selection(
        selection_add=[('paid', 'Paid')],
        ondelete={'paid': 'set default'},
    )
    elderly_reduction_line_ids = fields.One2many(
        'l10n_be.dmfa.elderly.reduction.line', 'dmfa_id',
        string="Elderly Reduction", readonly=True)
    artist_reduction_line_ids = fields.One2many(
        'l10n_be.dmfa.artist.reduction.line', 'dmfa_id',
        string="Artist reduction lines", readonly=True)
    unexperienced_reduction_line_ids = fields.One2many(
        'l10n_be.dmfa.unexperienced.reduction', 'dmfa_id',
        string='Unexperienced Employee Reductions')
    acs_deduction_line_ids = fields.One2many(
        'l10n_be.dmfa.acs.reduction.line', 'dmfa_id',
        string="ACS Reductions", readonly=True)
    declaration_type = fields.Selection([
        ('original', 'Original'),
        ('consultation', 'Consultation'),
        ('modification', 'Modification')
    ], string='Declaration Type', default='original', required=True)
    is_correction_needed = fields.Boolean()
    correction_reason = fields.Char(string='Justification')
    parent_id = fields.Many2one('l10n_be.dmfa', string='Original Declaration', index=True, help="A modified DMFA report has a link to the original report")
    children_ids = fields.One2many('l10n_be.dmfa', 'parent_id', help="The children are the modified versions of the original report")
    children_count = fields.Integer(compute='_compute_children_count')
    has_unfinished_modification = fields.Boolean(store=False, default=False, compute="_compute_has_unfinished_modification")

    first_hire_fields_invisible = fields.Boolean(compute='_compute_first_hire_fields_invisible')
    first_hire = fields.Many2one('hr.employee')
    first_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    first_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    first_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    second_hire = fields.Many2one('hr.employee')
    second_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    second_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    second_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    third_hire = fields.Many2one('hr.employee')
    third_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    third_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    third_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    fourth_hire = fields.Many2one('hr.employee')
    fourth_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    fourth_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    fourth_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    fifth_hire = fields.Many2one('hr.employee')
    fifth_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    fifth_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    fifth_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    sixth_hire = fields.Many2one('hr.employee')
    sixth_hire_disabled = fields.Boolean(compute='_compute_disabled_fields_and_messages')
    sixth_hire_message = fields.Char(default="", compute='_compute_disabled_fields_and_messages')
    sixth_hire_warning = fields.Char(default="", compute="_compute_is_invalid")
    first_hires_reductions_eligible_employee_ids = fields.Many2many('hr.employee', compute='_compute_first_hires_reductions_eligible_employee_ids')
    is_invalid = fields.Boolean(compute="_compute_is_invalid")

    @api.constrains('company_id', 'year', 'quarter')
    def _check_unique_dmfa(self):
        if self.declaration_type != 'original':
            return
        domain = [
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('year', '=', self.year),
            ('quarter', '=', self.quarter),
            ('declaration_type', '=', 'original'),
        ]
        same_quarter_reports = self.search(domain)
        if len(same_quarter_reports) > 0 and self.declaration_type == 'original':
            raise ValidationError(_("Only one DMFA per year/ quarter is allowed. Another one already exists."))

    @api.depends('children_ids')
    def _compute_has_unfinished_modification(self):
        for report in self:
            report.has_unfinished_modification = False
            for child in report.children_ids:
                if child.state not in ('done', 'refused'):
                    report.has_unfinished_modification = True
                    break

    @api.depends('children_ids')
    def _compute_children_count(self):
        for report in self:
            report.children_count = len(report.children_ids)

    def action_open_related_reports(self):
        self.ensure_one()
        return {
            'name': (self.name or "") + self.env._(' Updates'),
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_be.dmfa',
            'view_mode': 'list,form',
            'view_id': False,
            'target': 'current',
            'domain': [('id', 'in', self.children_ids.ids)],
        }

    @api.depends('company_id')
    def _compute_branch_ids(self):
        report_companies = self.mapped('company_id')
        branches_by_root = self.env['res.company'].search([
            ('id', 'child_of', report_companies.ids),
        ]).grouped('root_id')

        for report in self:
            report.branch_ids = branches_by_root.get(report.company_id, report.company_id)

    @api.model
    def action_list_view(self):
        if self.env.company.country_id.code != "BE":
            raise UserError(_('This feature seems to be as exclusive as Belgian chocolates. You must be logged in to a Belgian company to use it.'))
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_be_hr_payroll.hr_payslip_report_action_dmfa")
        action['context'] = {
            **literal_eval(action['context']),
            'onss_certificate_id': bool(self.env.company.onss_certificate_id),
        }
        return action

    def generate_reference_name(self):
        for dmfa in self:
            if config['test_enable'] or modules.module.current_test:
                continue
            allowed_chars = string.ascii_uppercase + string.digits
            dmfa.name = ''.join(random.choices(allowed_chars, k=13))

    @api.constrains('year')
    def _check_year(self):
        for dmfa in self:
            try:
                int(dmfa.year)
            except ValueError:
                raise ValidationError(_("Field Year does not seem to be a year. It must be an integer."))

    @api.constrains(*FIRST_HIRE_FIELDS)
    def _check_unique_hire_employees(self):
        for dmfa in self:
            selected_employees = self.env['hr.employee']
            for field in FIRST_HIRE_FIELDS:
                employee = dmfa[field]
                if employee:
                    if employee in selected_employees:
                        raise ValidationError(self.env._("You cannot select the same employee more than once."))
                    selected_employees |= employee

    @api.depends('dmfa_pdf')
    def _compute_pdf_filename(self):
        for dmfa in self:
            dmfa.dmfa_pdf_filename = 'FI' + dmfa._get_common_filename() + '.1.pdf'

    @api.depends('year', 'quarter')
    def _compute_dates(self):
        for dmfa in self:
            if not dmfa.year.isdigit() or len(dmfa.year) != 4:
                raise ValidationError(_("Please enter a valid year."))
            year = int(dmfa.year)
            month = int(dmfa.quarter) * 3
            dmfa.quarter_start, dmfa.quarter_end = date_utils.get_quarter(date(year, month, 1))

    @api.depends('quarter_end')
    def _compute_vehicle_ids(self):
        for dmfa in self:
            vehicles_assignment = self.env['fleet.vehicle.assignation.log'].sudo().search([
                ('vehicle_id.company_id', '=', dmfa.company_id.id),
                ('vehicle_id.license_plate', '!=', False),
                ('date_start', '<=', dmfa.quarter_end),
                '|', ('date_end', '>=', dmfa.quarter_start), ('date_end', '=', False),
                ('driver_id', '!=', False),
            ])
            dmfa.vehicle_ids = [(6, False, vehicles_assignment.vehicle_id.ids)]

    @api.depends('declaration_method')
    def _compute_state(self):
        # 'web' declarations are advanced manually through the form buttons; only batch ones are computed.
        batch_declarations = self.filtered(lambda d: d.declaration_method != 'web')
        super(__class__, batch_declarations)._compute_state()
        # an accepted modification corrects its original declaration
        batch_declarations.filtered(
            lambda d: d.declaration_type == 'modification' and d.state == 'done').parent_id.is_correction_needed = False

    @api.depends('company_id')
    def _compute_first_hire_fields_invisible(self):
        for dmfa in self:
            payroll_config = dmfa._get_payroll_config()
            dmfa.first_hire_fields_invisible = not payroll_config.l10n_be_reduction_for_first_hires

    @api.depends(*FIRST_HIRE_FIELDS, 'issues')
    def _compute_is_invalid(self):
        for dmfa in self:
            payroll_config = dmfa._get_payroll_config()
            onss_importance_code = payroll_config.onss_importance_code
            dmfa_payslips = dmfa.payslip_ids

            valid = True

            for field in FIRST_HIRE_FIELDS:
                warning = ''
                employee = dmfa[field]

                if employee and dmfa.quarter_start and dmfa.quarter_end:
                    payslips = dmfa_payslips.filtered(lambda p: p.employee_id == employee)
                    if payslips:
                        # TODO: Get rid of context keys, bind valus on natural person object instead
                        payslips_ctx = payslips.with_context(company_id=dmfa.company_id, dmfa_id=dmfa.id)
                        declaration_data = dmfa._get_declaration_data(payslips)
                        natural_person = DMFANaturalPerson(employee, payslips_ctx, dmfa.quarter_start, dmfa.quarter_end, onss_importance_code, declaration_data=declaration_data)
                        for worker_node in natural_person.worker_records:
                            reduction_node = worker_node.first_hire_reduction
                            if reduction_node:
                                actual_amount = float(reduction_node.deduction_amount) / 100.0

                                if actual_amount < reduction_node.reduction_cap:
                                    warning = dmfa.env._(
                                        'Only %(actual_amount)s reduced out of %(reduction_cap)s',
                                        actual_amount=actual_amount,
                                        reduction_cap=reduction_node.reduction_cap,
                                    )

                                work_rate = worker_node.mu_global * 100
                                if work_rate < 27.5:
                                    valid = False
                                    warning = dmfa.env._(
                                        "Not eligible (work rate of %(work_rate)s%% is less than the minimum of 27.5%%)",
                                        work_rate=work_rate,
                                    )
                                break

                dmfa[f'{field}_warning'] = warning

            # If a company was elegible for reductions for 4th, 5th or 6th hire before 1/1/2024, the employees selected
            # for that reduction have to be hired before 2024
            for field in FIRST_HIRE_FIELDS[3:]:
                date_of_eligibility = payroll_config[f'l10n_be_{field}_reduction_eligibility_date']
                if not date_of_eligibility:
                    date_of_eligibility = dmfa.quarter_start
                if date_of_eligibility > date(2023, 12, 31):
                    continue
                is_eligible = dmfa._is_eligible_for_fourth_to_sixth_hire_reduction_before_2024(dmfa[field])
                if not is_eligible:
                    dmfa[f'{field}_warning'] = dmfa.env._('Not eligible (not hired before 1/1/2024)')
                valid &= is_eligible

            dmfa.is_invalid = not valid or any(issue['level'] == 'danger' for issue in (dmfa.issues or {}).values())

    @api.depends(*FIRST_HIRE_FIELDS[1:], 'state', 'year', 'quarter')
    def _compute_disabled_fields_and_messages(self):
        for dmfa in self:
            dmfa.first_hire_message = dmfa.env._("Unlimited")
            dmfa.first_hire_disabled = dmfa.state != 'draft'
            payroll_config = dmfa._get_payroll_config()

            dmfa_reports = self.env['l10n_be.dmfa'].search(
                domain=[('company_id', '=', dmfa.company_id.id)],
                order='year asc, quarter asc',
            )

            for field in FIRST_HIRE_FIELDS[1:]:
                date_of_eligibility = payroll_config[f'l10n_be_{field}_reduction_eligibility_date'] or dmfa.quarter_start

                is_abolished = False
                if date_of_eligibility:
                    if (field == 'sixth_hire' and date_of_eligibility >= date(2024, 1, 1)) or (field in ('fourth_hire', 'fifth_hire') and date(2024, 1, 1) <= date_of_eligibility < date(2026, 7, 1)):
                        is_abolished = True

                if is_abolished:
                    dmfa[f'{field}_message'] = ''  # This signifies that the field should be invisible
                    dmfa[f'{field}_disabled'] = True
                    continue

                def _quarter_diff(eligibility_date, dmfa_date):
                    if not eligibility_date:
                        eligibility_date = dmfa_date
                    return (dmfa_date.year - eligibility_date.year) * 4 + (dmfa_date.month - eligibility_date.month) // 3

                values = [bool(report[field]) for report in dmfa_reports if report.state == 'done']
                num_usages = values.count(True)
                quarters_since_first_occurrence = _quarter_diff(date_of_eligibility, dmfa.quarter_start) if date_of_eligibility and dmfa.quarter_start else 0

                is_disabled = False
                message = ''

                window_cap = payroll_config[f'l10n_be_{field}_reduction_window_cap']
                reductions_used_outside_odoo = payroll_config[f'l10n_be_{field}_reductions_used_outside_odoo']
                allowed_reduction_count = dmfa._get_applicable_first_hires_rule_parameter_values(field)[-1]['max_quarter']
                count_cap = allowed_reduction_count - reductions_used_outside_odoo

                if quarters_since_first_occurrence > window_cap or window_cap == 0:
                    is_disabled = True
                    message = dmfa.env._('Window expired')
                elif num_usages >= count_cap:
                    is_disabled = True
                    message = dmfa.env._("0 quarters left")
                else:
                    message = dmfa.env._(
                        '%(quarters_left)s quarters left',
                        quarters_left=count_cap - num_usages,
                    )

                if dmfa.state != 'draft':
                    is_disabled = True

                dmfa[f'{field}_disabled'] = is_disabled
                dmfa[f'{field}_message'] = message

    @api.onchange('year', 'quarter')
    def _onchange_period(self):
        for dmfa in self:
            for field in FIRST_HIRE_FIELDS:
                dmfa[field] = False

    def _get_payroll_config(self):
        return self.company_id._get_payroll_config(self.quarter_start)

    def _get_applicable_first_hires_rule_parameter_values(self, field):
        rule_date = None
        payroll_config = self._get_payroll_config()
        if field == FIRST_HIRE_FIELDS[0]:
            rule_date = self.quarter_start
        else:
            eligibility_date = payroll_config[f'l10n_be_{field}_reduction_eligibility_date']
            rule_date = eligibility_date if eligibility_date else self.quarter_start

        return self.env['hr.rule.parameter']._get_parameter_from_code(f'{field}_contribution_reduction', rule_date)

    def _is_eligible_for_fourth_to_sixth_hire_reduction_before_2024(self, employee):
        if not employee:
            return True

        versions = employee._get_first_versions().filtered(lambda v: v.l10n_be_dimona_category not in ['stu', 'flx'])  # exclude flexi and student versions
        if not versions:
            return False
        first_version_date = min(versions.mapped('date_start'))
        return first_version_date <= date(2023, 12, 31)

    def action_open_report_employees_wizard(self):
        self.ensure_one()
        return {
            'name': 'Select Employees',
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_be.dmfa.employees.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_dmfa_id': self.id,
            }
        }

    def _pre_submit_checks(self):
        errors = super()._pre_submit_checks()
        if self.declaration_type == 'consultation' and self.environment != 'R':
            errors.append(self.env._("Consultation Requests can only be posted in production environment."))
        return errors

    def _update_payroll_config_eligibility_dates(self):
        for dmfa in self:
            dmfa_date = dmfa.quarter_start
            payroll_config = dmfa.company_id._get_payroll_config(dmfa_date)
            for field in FIRST_HIRE_FIELDS[1:]:
                if dmfa[field]:
                    payroll_config_field = payroll_config[f'l10n_be_{field}_reduction_eligibility_date']
                    payroll_config[f'l10n_be_{field}_reduction_eligibility_date'] = min(payroll_config_field, dmfa_date) if payroll_config_field else dmfa_date

    def _skip_blocking_issues_check(self):
        return self.declaration_type == 'consultation' or (self.declaration_type == 'modification' and self.declaration_method == 'batch')

    def generate_declaration_xml_report(self):
        self._update_payroll_config_eligibility_dates()
        self.generate_reference_name()
        return super().generate_declaration_xml_report()

    def generate_dmfa_pdf_report(self):
        self._update_payroll_config_eligibility_dates()
        dmfa_pdf, dummy = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            'l10n_be_hr_payroll.action_report_dmfa', res_ids=self.ids)
        self.dmfa_pdf = BinaryBytes(dmfa_pdf)
        self.state = 'ready'
        self.payslip_ids.l10n_be_dmfa_id = self.id

    def prefill_first_hires(self):
        self.ensure_one()
        payslips = self.payslip_ids
        work_entry_types = payslips.mapped('worked_days_line_ids.work_entry_type_id')
        invalid_types = work_entry_types.filtered(lambda t: not t.dmfa_code)
        if invalid_types:
            raise UserError(self.env._('The following work entry types do not have any DMFA code set:\n %s', '\n'.join(invalid_types.mapped('name'))))

        for field in FIRST_HIRE_FIELDS:
            self[field] = False

        employee_payslips = defaultdict(lambda: self.env['hr.payslip'])
        payslips_ctx = payslips.with_context(company_id=self.company_id, dmfa_id=self.id)
        for payslip in payslips_ctx:
            employee_payslips[payslip.employee_id] |= payslip

        employees = list(employee_payslips.keys())
        if not employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('There are no payslips in this quarter so no employee is eligible for First Hires Reduction.'),
                    'type': 'warning',
                },
            }

        payroll_config = self._get_payroll_config()
        declaration_data = self._get_declaration_data(payslips)
        worker_records = DMFAWorker.init_multi([
            (employee_payslips[emp], self.quarter_start, self.quarter_end, payroll_config.onss_importance_code, None, False, declaration_data)
            for emp in employees
        ])

        employee_data = []
        for worker_record, employee in zip(worker_records, employees):
            if worker_record.mu_global * 100 < 27.5:
                continue

            potential_reduction = DMFAFirstHireReduction._calculate_potential_reduction(
                worker_record.contributions,
                worker_record.deductions,
                worker_record._get_occupation_deductions(),
            )
            hired_before_2024 = self._is_eligible_for_fourth_to_sixth_hire_reduction_before_2024(employee)
            employee_data.append({
                'employee': employee,
                'reduction': potential_reduction,
                'hired_before_2024': hired_before_2024,
            })

        if not employee_data:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('There are no eligible employees with sufficient work rate (>= 27.5%) in this quarter.'),
                    'type': 'warning',
                },
            }

        employee_data.sort(key=lambda x: x['reduction'], reverse=True)

        assigned_employees = self.env['hr.employee']

        for field in FIRST_HIRE_FIELDS:
            if self[f'{field}_disabled']:
                continue

            requires_pre_2024 = False
            if field in FIRST_HIRE_FIELDS[3:]:
                company_eligibility_date = payroll_config[f'l10n_be_{field}_reduction_eligibility_date']
                if company_eligibility_date and company_eligibility_date <= date(2023, 12, 31):
                    requires_pre_2024 = True

            for data in employee_data:
                employee = data['employee']
                if employee in assigned_employees:
                    continue
                if requires_pre_2024 and not data['hired_before_2024']:
                    continue

                self[field] = employee
                assigned_employees |= employee
                break

        if not assigned_employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('No employee could be assigned to the enabled reduction slots.'),
                    'type': 'warning',
                },
            }

        return None

    def _get_declaration_data(self, payslips):
        """ Values needed by several nodes of the declaration, computed once for all of them """
        # Read the lines of all the payslips at once. Read occupation by occupation, each cache miss
        # would go through the lines of all the payslips (their prefetch set) to find the ones to read.
        # As superuser, as the payslips are already filtered by the access rules: checking those of the
        # lines computes their non-stored company_id, going through all the lines on each batch. Only
        # their ids are kept: the nodes read the lines (in cache) as the current user.
        lines_sudo = self.env['hr.payslip.line'].sudo().search_fetch(
            [('slip_id', 'in', payslips.ids)], ['slip_id', 'code', 'total', 'salary_rule_id'])
        payslip_lines = defaultdict(list)
        for line_sudo in lines_sudo:
            payslip_lines[line_sudo.slip_id.id].append(line_sudo.id)

        return {
            'payslip_lines': payslip_lines,
            'mobility_payments': {p.id: any(line.code in ('MOBILITY_PAYMENT', 'MOBILITY_PAYMENT_PREV_YEAR') for line in p.input_line_ids) for p in payslips},
            # env.ref() checks that the record exists with a query on each call
            'salary_rules': {
                'regular_gross': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_gross_salary'),
                'commission_gross': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_fixed_commission'),
                'holiday_pay_regularization_n': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_holiday_pay_regularization_n', raise_if_not_found=False),
                'atn_corr_1': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_atn_corr_code_1'),
                'atn_corr_2': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_atn_corr_code_2'),
                'flexi_bonus': self.env.ref('l10n_be_hr_payroll.cp200_employees_salary_flexi_bonus'),
            },
        }

    def _get_rendering_data(self):
        self.ensure_one()
        if self.declaration_type == 'consultation':
            return self._get_consultation_rendering_data()
        if self.declaration_type == 'modification' and self.declaration_method == 'batch':
            return self._get_modification_rendering_data()
        payslips = self.payslip_ids

        if self.has_blocking_issues:
            raise UserError(self.env._("Fix the validation errors before creating the report."))

        payroll_config = self._get_payroll_config()

        eco_vehicle_values = payslips._get_line_values(['ONSSEMPLOYER_868'])['ONSSEMPLOYER_868']
        eco_vehicles = payslips.filtered(lambda p: eco_vehicle_values[p.id]['total'] > 0).vehicle_id

        payslips_by_niss = defaultdict(lambda: self.env['hr.payslip'])
        employees_by_niss = defaultdict(lambda: self.env['hr.employee'])
        for payslip in payslips:
            employee = payslip.employee_id
            niss = employee.niss
            payslips_by_niss[niss] |= payslip
            employees_by_niss[niss] |= employee

        natural_person_states = self.env['l10n_be.dmfa.natural_person.state'].search([('niss', 'in', employees_by_niss.keys()),
                    ('quarter_start', '=', self.quarter_start), ('quarter_end', '=', self.quarter_end)])
        natural_person_state_map = {state.employee_id: state for state in natural_person_states}

        declaration_data = self._get_declaration_data(payslips)

        natural_person_args = []
        for niss, person_payslips in payslips_by_niss.items():
            canonical_employee = (employees_by_niss[niss].filtered('active') or employees_by_niss[niss]).sorted('id')[0]
            natural_person_args.append((
                canonical_employee,
                person_payslips.with_context(company_id=self.company_id, dmfa_id=self.id),
                self.quarter_start,
                self.quarter_end,
                payroll_config.onss_importance_code,
                'dmfa',
                natural_person_state_map.get(canonical_employee),
                declaration_data,
            ))
        natural_person_args.sort(key=lambda args: args[0].id)

        target_date = date.today() - relativedelta(months=3)
        target_quarter = (target_date.month - 1) // 3 + 1
        current_year_quarter = '%s%s' % (target_date.year, target_quarter)

        natural_person_args.sort(key=lambda x: x[0].id)

        result = {
            'employer_class': payroll_config.l10n_be_employer_category_id.dmfa_code,
            'l10n_be_company_number': format_amount(payroll_config.l10n_be_company_number or 0, width=10, hundredth=False),
            'onss_registration_number': format_amount(payroll_config.onss_registration_number or 0, width=9, hundredth=False),
            'quarter_repr': '%s%s' % (self.year, self.quarter),
            'quarter_display': '%s/%s' % (self.year, self.quarter),
            'quarter_start': self.quarter_start,
            'quarter_end': self.quarter_end,
            'data': self,
            'system5': 0,
            'holiday_starting_date': -1,
            'natural_persons': DMFANaturalPerson.init_multi(natural_person_args),
            'pretty_format': lambda a: str(round(int(a) / 100.0, 2)),
            'vehicles': DMFACompanyVehicle.init_multi([(vehicle, eco_vehicles) for vehicle in self.vehicle_ids]),
            'schema_year_quarter': current_year_quarter,
            'company_contributions': self._prepare_company_contributions(payslips)
        }
        self._check_occupation_dates(result['natural_persons'])
        self._check_occupations_without_hours(result['natural_persons'])

        # Special employer contribution reduction due to 2023 index
        contribution_reduction = 0
        if self.quarter_start.year == 2023 and self.quarter_start.month < 5:
            # The 7.07% contribution reduction is calculated on the overall net basic
            # employer contributions. These are the employer contributions calculated
            # on all the remuneration codes on which the basic employer contributions
            # are calculated (remuneration codes 1, 2, 3, 4, 5, 6, 7, 9, 51, 61, 62,
            # 65 and 66 ) after deduction of applicable employer contribution reductions
            # with the exception of the maribel social package.
            # Source: https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/deductions/otheremployersreductions/competitivity_reduction.html
            total_employer_contribution = 0
            # Sum all employer contributions
            for natural_person in result['natural_persons']:
                for worker_record in natural_person.worker_records:
                    for contribution in worker_record.contributions:
                        total_employer_contribution += int(contribution.amount) / 100.0
                    for contribution in worker_record.student_contributions:
                        total_employer_contribution += int(contribution.student_contribution_amount) / 100.0
            # Sum all employee deductions
            for natural_person in result['natural_persons']:
                for worker_record in natural_person.worker_records:
                    for deduction in worker_record.deductions:
                        total_employer_contribution -= int(deduction.amount) / 100.00
            contribution_reduction = round(total_employer_contribution * 7.07 / 100, 2)
            result['employer_compensation'] = format_amount(contribution_reduction)
        else:
            result['employer_compensation'] = 0

        contribution_summary = self._get_contribution_summary(result['natural_persons'], result['company_contributions'], format_amount(contribution_reduction))
        result['global_contribution'] = format_amount(contribution_summary['contribution_summary'])
        result['employer_contributions_summary'] = contribution_summary['employer_contributions']
        result['worker_deductions_summary'] = contribution_summary['worker_deductions']

        self._generate_elderly_reduction_lines(result['natural_persons'])
        self._generate_artist_reduction_lines(result['natural_persons'])
        self._generate_unexperienced_reduction_lines(result['natural_persons'])
        self._generate_acs_deduction_lines(result['natural_persons'])
        return result

    def _check_occupation_dates(self, natural_persons):
        """ The ONSS refuses the occupations starting after the quarter, ending before it, or ending
        before they start (except the periods covered by a termination indemnity, after the quarter) """
        invalid_employees = self.env['hr.employee']
        for natural_person in natural_persons:
            for worker_record in natural_person.worker_records:
                for occupation in worker_record.occupations:
                    if occupation.is_termination:
                        continue
                    date_start, date_stop = occupation.date_start, occupation.date_stop
                    if date_start > self.quarter_end or (date_stop and (date_stop < self.quarter_start or date_stop < date_start)):
                        invalid_employees |= natural_person.employee
        if invalid_employees:
            raise UserError(self.env._(
                "The occupations of these employees aren't in the quarter, check their contract dates "
                "and the dates of their payslips: %(names)s", names=", ".join(invalid_employees.mapped('name'))))

    def _check_occupations_without_hours(self, natural_persons):
        """ The ONSS refuses the services declared on an occupation without hours per week (a full
        time credit or career interruption): blocking anomaly 90018-094. They come from payslips with
        worked days on such a version, for instance computed before its working schedule changed. """
        invalid_occupations = []
        for natural_person in natural_persons:
            for worker_record in natural_person.worker_records:
                for occupation in worker_record.occupations:
                    # Without the periods covered by a termination indemnity
                    services = [s for s in occupation.services if s.sequence != 99]
                    # A working schedule whose hours per week aren't set isn't a suspension
                    if services and not int(occupation.mean_working_hours) and occupation.contract.l10n_be_time_credit:
                        invalid_occupations.append(self.env._(
                            "%(employee)s, from %(date_from)s to %(date_to)s (version %(version)s): services %(codes)s",
                            employee=natural_person.employee.name,
                            date_from=occupation.date_start,
                            date_to=occupation.date_stop or '...',
                            version=occupation.contract.id,
                            codes=', '.join(s.code for s in services)))
        if invalid_occupations:
            raise UserError(self.env._(
                "Services are declared on occupations without hours per week, which the ONSS refuses. Check that the "
                "worked days of their payslips match the working schedule of their version (a payslip computed before "
                "a change of the version):\n%(occupations)s", occupations='\n'.join(invalid_occupations)))

    def _get_consultation_rendering_data(self):
        employees_to_consult = self.env.context.get('employees_to_report')
        if not employees_to_consult:
            employees_to_consult = self.env['hr.employee'].search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True)])

        employees = employees_to_consult
        payroll_config = self._get_payroll_config()

        #### Preliminary Checks ####
        # Check Valid ONSS denominations
        if not payroll_config.l10n_be_employer_category_id.dmfa_code:
            raise ValidationError(_("Please provide an employer class for company %s. The employer class is given by the ONSS and should be encoded in the Payroll setting.", self.company_id.name))
        if not payroll_config.onss_registration_number and not payroll_config.l10n_be_company_number:
            raise ValidationError(_("No ONSS registration number nor company ID was found for company %s. Please provide at least one.", self.company_id.name))
        # Check valid NISS
        invalid_employees = employees.filtered(lambda e: not e._is_niss_valid())
        if invalid_employees:
            raise UserError(_('Invalid NISS number for those employees:\n %s', '\n'.join(invalid_employees.mapped('name'))))

        natural_person_args = []

        natural_person_states = self.env['l10n_be.dmfa.natural_person.state'].search([('employee_id', 'in', employees.ids),
                    ('quarter_start', '=', self.quarter_start), ('quarter_end', '=', self.quarter_end)])
        natural_person_state_map = {state.employee_id: state for state in natural_person_states}

        for employee in employees:
            natural_person_args.append((
                employee,
                None,
                self.quarter_start,
                self.quarter_end,
                0,
                'consultation',
                natural_person_state_map.get(employee.id),
            ))

        target_date = date.today() - relativedelta(months=3)
        target_quarter = (target_date.month - 1) // 3 + 1
        current_year_quarter = '%s%s' % (target_date.year, target_quarter)

        natural_person_args.sort(key=lambda x: x[0].id)

        result = {
            'quarter_repr': '%s%s' % (self.year, self.quarter),
            'onss_registration_number': format_amount(payroll_config.onss_registration_number or 0, width=9, hundredth=False),
            'l10n_be_company_number': format_amount(payroll_config.l10n_be_company_number or 0, width=10, hundredth=False),
            'natural_persons': DMFANaturalPerson.init_multi(natural_person_args),
            'schema_year_quarter': current_year_quarter,
        }

        return result

    def _get_modification_rendering_data(self):
        employees_to_modify = self.env.context.get('employees_to_report')
        if not employees_to_modify:
            employees_to_modify = self.env['hr.employee'].search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True)])

        valid_states = self.env['l10n_be.dmfa.natural_person.state'].search([
            ('employee_id', 'in', employees_to_modify.ids),  # Ensure there is a linked employee
            ('natural_person_pid', '!=', False),
            ('quarter_start', '=', self.quarter_start),
            ('quarter_end', '=', self.quarter_end),
        ])

        employees_with_valid_states = valid_states.mapped('employee_id')

        employees = employees_with_valid_states

        payslips = self.env['hr.payslip'].search([
            ('employee_id', 'in', employees.ids),
            ('date_to', '>=', self.quarter_start),
            ('date_to', '<=', self.quarter_end),
            ('state', 'in', ['validated', 'paid']),
            ('company_id', '=', self.company_id.id),
        ])
        warrant_structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant')
        # Exclude CIP contracts from DmfA, as they only have a DIMONA
        valid_structure_type = self.env.ref('hr.structure_type_employee_cp200')
        payslips = payslips.filtered(
            lambda p: (
                p.version_id.l10n_be_worker_code_id.dmfa_code not in ['848', '849']
                and p.version_id.structure_type_id == valid_structure_type
                and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
                and (p.struct_id != warrant_structure or p._get_input_line_amount('WARRANT_WITH_ONSS'))
            )
        )
        employees = payslips.mapped('employee_id')
        payroll_config = self._get_payroll_config()

        #### Preliminary Checks ####
        # Check Valid ONSS denominations
        if not payroll_config.l10n_be_employer_category_id.dmfa_code:
            raise ValidationError(_("Please provide an employer class for company %s. The employer class is given by the ONSS and should be encoded in the Payroll setting.", self.company_id.name))
        if not payroll_config.onss_registration_number and not payroll_config.l10n_be_company_number:
            raise ValidationError(_("No ONSS registration number nor company ID was found for company %s. Please provide at least one.", self.company_id.name))
        # Check valid NISS
        invalid_employees = employees.filtered(lambda e: not e._is_niss_valid())
        if invalid_employees:
            raise UserError(_('Invalid NISS number for those employees:\n %s', '\n'.join(invalid_employees.mapped('name'))))
        # Check valid work addresses
        work_addresses = payslips.version_id.address_id
        location_units = self.env['hr.work.location'].search([('address_id', 'in', work_addresses.ids), ('location_type', '=', 'dmfa_unit')])
        invalid_addresses = work_addresses - location_units.mapped('address_id')
        invalid_employees = payslips.version_id.filtered(lambda v: v.address_id in invalid_addresses).employee_id
        if invalid_addresses:
            raise UserError(_('Employees with work address missing ONSS code %s', '\n'.join(invalid_employees.mapped('name'))))
        # Check valid work entry types
        work_entry_types = payslips.mapped('worked_days_line_ids.work_entry_type_id')
        invalid_types = work_entry_types.filtered(lambda t: not t.dmfa_code)
        if invalid_types:
            raise UserError(_('The following work entry types do not have any DMFA code set:\n %s', '\n'.join(invalid_types.mapped('name'))))

        payslips_by_niss = defaultdict(lambda: self.env['hr.payslip'])
        employees_by_niss = defaultdict(lambda: self.env['hr.employee'])
        for payslip in payslips:
            employee = payslip.employee_id
            niss = employee.niss
            payslips_by_niss[niss] |= payslip
            employees_by_niss[niss] |= employee
        worker_count = len(employees_by_niss)

        natural_person_states = self.env['l10n_be.dmfa.natural_person.state'].search([
            ('niss', 'in', employees_by_niss.keys()),
            ('quarter_start', '=', self.quarter_start),
            ('quarter_end', '=', self.quarter_end),
            ('natural_person_pid', '!=', "")
        ])
        # TODO: we don't sync data yet, so if data is returned for the consultation for an employee with no payslips on odoo, it won't be detected.
        natural_person_state_map = {state.employee_id: state for state in natural_person_states}

        declaration_data = self._get_declaration_data(payslips)

        natural_person_args = []
        for niss, payslips in payslips_by_niss.items():
            canonical_employee = (employees_by_niss[niss].filtered('active') or employees_by_niss[niss]).sorted('id')[0]
            natural_person_args.append((
                canonical_employee,
                payslips,
                self.quarter_start,
                self.quarter_end,
                worker_count,
                'modification',
                natural_person_state_map.get(canonical_employee),
                declaration_data,
            ))

        if not self.parent_id.company_pid:
            raise ValidationError(_("Unable to find the EmployerDeclarationPID for the original declaration."))

        target_date = date.today() - relativedelta(months=3)
        target_quarter = (target_date.month - 1) // 3 + 1
        current_year_quarter = '%s%s' % (target_date.year, target_quarter)

        natural_person_args.sort(key=lambda x: x[0].id)

        # Here we rely on the natural NaturalPersonState model instead of NaturalPerson; to render data retrieved from the consultation
        result = {
            'data': self,
            'employer_class': payroll_config.l10n_be_employer_category_id.dmfa_code,
            'quarter_repr': '%s%s' % (self.year, self.quarter),
            'onss_registration_number': format_amount(payroll_config.onss_registration_number or 0, width=9, hundredth=False),
            'l10n_be_company_number': format_amount(payroll_config.l10n_be_company_number or 0, width=10, hundredth=False),
            'onss_employer_declaration_id': self.parent_id.company_pid,
            'system5': '0',
            'natural_persons': DMFANaturalPerson.init_multi(natural_person_args),
            'schema_year_quarter': current_year_quarter,
        }
        self._check_occupations_without_hours(result['natural_persons'])

        return result

    def action_post_onss_declaration(self):
        res = super().action_post_onss_declaration()
        self.payslip_ids.l10n_be_dmfa_id = self.id
        return res

    def _prepare_company_contributions(self, payslips):
        contributions_values = []

        # Cotisation due sur les participations aux bénéfices
        profit_sharing_basis, profit_sharing_onss = self._get_profit_sharing_contribution(payslips)
        if profit_sharing_onss != 0:
            contributions_values.append((payslips, '861', self.env._('Contribution due on profit-sharing'), profit_sharing_onss, profit_sharing_basis))

        # En DMFA et en DMFAPPL, la cotisation de solidarité sur l'usage personnel d'un véhicule de
        # société se déclare globalement par catégorie d'employeur dans le bloc 90002 « cotisation
        # non liée à une personne physique» sous le code travailleur 862.
        # NB : Il est autorisé de rassembler les données de toute l'entreprise sous une seule
        # catégorie.
        # De plus, dans le bloc fonctionnel 90294 « Véhicule de société », la mention des numéros de
        # plaque des véhicules concernés est obligatoire. Un même numéro d'immatriculation ne peut
        # être repris qu'une seule fois.
        # L'avantage perçu par le travailleur pour l'usage d'un véhicule de société doit également
        # être déclaré  sous  le code rémunération DMFA 10  ou le code rémunération DMFAPPL 770 dans
        # le bloc fonctionnel 90019 "Rémunération de l'occupation ligne travailleur".
        # Lorsque la DMFA ou la DMFAPPL  est introduite via le web, le montant global de cette
        # cotisation doit être mentionné dans les cotisations dues pour l'ensemble de l'entreprise,
        # les numéros de plaques des véhicules concernés introduits dans l'écran prévu et
        # l'avantage déclaré avec les rémunérations du travailleur.
        vehicle_onss = self._get_vehicles_contribution()
        if vehicle_onss != 0:
            contributions_values.append((payslips, '862', self.env._('Company Cars Global Contributions'), vehicle_onss))

        # https://www.socialsecurity.be/employer/instructions/dmfa/fr/latest/instructions/special_contributions/extralegal_pensions.html#h24
        # En DMFA, la cotisation sur les avantages extra-légaux se déclare globalement par catégorie
        # d’employeur dans le bloc 90002 « cotisation non liée à une personne physique» sous les codes
        # travailleur 864, 865 ou 866 selon le cas.

        # 864 : pour les versements effectués directement au travailleur pensionné ou à ses ayants
        #       droit
        # 865 : pour les versements destinés au financement d'une pension complémentaire dans le cadre
        #       d'un plan d'entreprise
        # 866 : pour les versements destinés au financement d'une pension complémentaire dans le cadre
        #       d'un plan sectoriel
        # ! à partir du 1/2014, cotisation 866 déclarée uniquement par l'organisateur du régime
        #   sectoriel (catégorie X99)
        # Jusqu'au 3ème trimestre 2011 inclus, le code travailleur 851 était d'application mais il
        # n'est plus autorisé pour les trimestres ultérieurs.

        # La base de calcul qui correspond à la somme des avantages octroyés pour l’entreprise par
        # type de versement doit être mentionnée.

        # Lorsque la DMFA est introduite via le web, la base de calcul de cette cotisation doit être
        # mentionnée dans les cotisations dues pour l’ensemble de l’entreprise et la cotisation est
        # calculée automatiquement.
        group_basis, group_onss = self._get_group_insurance_contribution()
        if group_onss != 0:
            contributions_values.append((payslips, '865', self.env._('Group Insurance Global Contributions'), group_onss, group_basis))

        # The Wijninckx contribution on the high extra-legal pensions is declared globally (block 90002
        # "cotisation non liée à une personne physique"), in the 4th quarter only
        wijninckx_amount = round(payslips._get_line_values(['ONSSEMPLOYER_867'], compute_sum=True)['ONSSEMPLOYER_867']['sum']['total'], 2)
        if wijninckx_amount:
            if self.quarter_start.month != 10:
                raise UserError(self.env._('Wijninckx contribution should only be declared on the last quarter of the year'))
            wijninckx_basis = round(sum(payslip._get_input_line_amount('ONSSEMPLOYER_867') for payslip in payslips), 2)
            contributions_values.append((payslips, str(WIJNINCKX), self.env._('Wijninckx Contribution'), wijninckx_amount, wijninckx_basis))

        double_basis, double_onss = self._get_double_holiday_pay_contribution(payslips)
        if double_onss != 0:
            contributions_values.append((payslips, '870', self.env._('Double Holiday Pay Global Contributions'), double_onss, double_basis))

        return DMFACompanyContributions.init_multi(contributions_values)

    def _get_contribution_summary(self, employees_infos, company_contributions, contribution_reduction):
        """ Sum of all the owed contributions to ONSS"""

        def _format_basis(value):
            return 0 if value == -1 else int(value) / 100

        total = - int(contribution_reduction) / 100.0

        contributions = defaultdict(lambda: [0, 0])
        deductions = defaultdict(lambda: [0, 0])

        for natural_person in employees_infos:
            for worker_record in natural_person.worker_records:
                worker_code = worker_record.worker_code

                # Employee contributions
                for contribution in worker_record.contributions:
                    amount = int(contribution.amount) / 100.0
                    total += amount
                    key = (contribution.worker_code, contribution.contribution_type)
                    contributions[key][0] += _format_basis(contribution.calculation_basis)
                    contributions[key][1] += amount

                # Employee contributions (students)
                for contribution in worker_record.student_contributions:
                    amount = int(contribution.student_contribution_amount) / 100.0
                    total += amount
                    key = (worker_code, -1)
                    contributions[key][0] += _format_basis(contribution.student_remun_amount)
                    contributions[key][1] += amount

                # Employee deductions (worker level)
                for deduction in worker_record.deductions:
                    amount = int(deduction.amount) / 100.0
                    total -= amount
                    key = (worker_code, deduction.code)
                    deductions[key][0] += _format_basis(deduction.deduction_calculation_basis)
                    deductions[key][1] += amount

                # Employee deductions (occupation level)
                for occupation in worker_record.occupations:
                    for occupation_deduction in occupation.occupation_deductions:
                        amount = int(occupation_deduction.deduction_amount) / 100.0
                        total -= amount
                        key = (worker_code, occupation_deduction.deduction_code)
                        deductions[key][0] += _format_basis(occupation_deduction.deduction_calculation_basis)
                        deductions[key][1] += amount

        # Employer contributions (unrelated to Natural Person):
        for cc in company_contributions:
            total = total + int(cc.amount) / 100.0

        contributions_summary = [
            {
                'code': code,
                'contribution_type': contribution_type,
                'basis': round(basis, 2),
                'amount': round(amount, 2),
            }
            for (code, contribution_type), (basis, amount) in contributions.items()
            ]
        deductions_summary = [
            {
                'worker_code': worker_code,
                'code': code,
                'basis': round(basis, 2),
                'amount': round(amount, 2),
            }
            for (worker_code, code), (basis, amount) in deductions.items()
        ]

        return {
            'contribution_summary': round(total, 2),
            'employer_contributions': contributions_summary,
            'worker_deductions': deductions_summary,
        }

    def _get_vehicles_contribution(self):
        self.ensure_one()
        payslips_sudo = self.env['hr.payslip'].sudo().search([
            ('date_to', '>=', self.quarter_start),
            ('date_to', '<=', self.quarter_end),
            ('state', 'in', ['validated', 'paid']),
            ('struct_id', '=', self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary').id),
            ('company_id', 'child_of', self.branch_ids.ids),
        ])

        # CO2 fees that already declared & paid on employee monthly payslips
        payslip_co2_fees = payslips_sudo._get_line_values(['CO2FEE'], compute_sum=True)['CO2FEE']['sum']['total']

        payslip_vehicles_by_month = {}
        for payslip in payslips_sudo.filtered(lambda p: p.vehicle_id):
            payslip_vehicles_by_month.setdefault(payslip.date_from, set()).add(payslip.vehicle_id.id)

        # CO2 fees for pool cars
        pool_co2_fees = 0.0
        current_month = self.quarter_start
        for month_idx in range(3):
            covered_vehicle_ids = payslip_vehicles_by_month.get(current_month, set())

            pool_vehicles_assignment = self.env['fleet.vehicle.assignation.log'].sudo().search([
                ('vehicle_id.company_id', '=', self.company_id.id),
                ('vehicle_id.license_plate', '!=', False),
                ('vehicle_id.id', 'not in', list(covered_vehicle_ids)),
                ('date_start', '<=', current_month + relativedelta(months=1, days=-1)),
                '|', ('date_end', '>=', current_month), ('date_end', '=', False),
                ('driver_id', '!=', False),
            ])

            pool_vehicles = pool_vehicles_assignment.vehicle_id

            pool_co2_fees += sum(
                vehicle.with_context(co2_fee_date=current_month)._get_co2_fee(
                    vehicle.co2, vehicle.co2_emission_unit, vehicle.fuel_type
                )
                for vehicle in pool_vehicles
            )

            current_month += relativedelta(months=1)

        return round(payslip_co2_fees + pool_co2_fees, 2)

    def _get_double_holiday_pay_contribution(self, payslips):
        """ Some contribution are not specified at the worker level but globally for the whole company """
        # Montant de la cotisation exceptionnelle (code 870)
        payslips = payslips.filtered(lambda p: not p.version_id.no_onss)

        double_holiday_struct_codes = ['BEMONTHLY', 'BEDOUBLE', 'BEHOLN', 'BEHOLN1']
        gross_salary_codes = ['DH_SALARY', 'PAY_DOUBLE']
        payslips = payslips.filtered(lambda p: p.struct_id.code in double_holiday_struct_codes)
        line_values = payslips._get_line_values(gross_salary_codes)
        basis_raw = sum(sum(line_values[code][p.id]['total'] for code in gross_salary_codes) for p in payslips)
        basis = round(basis_raw, 2)
        onss_amount = round(basis_raw * 0.1307, 2)
        return (basis, onss_amount)

    def _get_profit_sharing_contribution(self, payslips):
        payslips = payslips.filtered(lambda p: not p.version_id.no_onss and p.struct_id.code == 'BEPROFITSHARING')
        line_values = payslips._get_line_values(['PROFITSHARING_SALARY'], vals_list=['total'], compute_sum=True)
        basis = line_values['PROFITSHARING_SALARY']['sum']['total']
        onss_amount = round(basis * 0.1307, 2)
        return (round(basis, 2), onss_amount)

    def _get_group_insurance_contribution(self):
        regular_payslip = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary')
        payslips_sudo = self.env['hr.payslip'].sudo().search([
            ('date_to', '>=', self.quarter_start),
            ('date_to', '<=', self.quarter_end),
            ('state', 'in', ['validated', 'paid']),
            ('struct_id', '=', regular_payslip.id),
            ('company_id', 'in', self.branch_ids.ids),
        ])
        line_values = payslips_sudo._get_line_values(
            ['GROUPINSURANCE'], vals_list=['amount', 'total'], compute_sum=True
        )
        basis = line_values['GROUPINSURANCE']['sum']['amount']
        onss_amount = line_values['GROUPINSURANCE']['sum']['total']
        return (round(basis, 2), round(onss_amount, 2))

    @api.depends('onss_declaration_ids')
    def _compute_onss_declaration_count(self):
        for dmfa in self:
            dmfa.onss_declaration_count = len(dmfa.onss_declaration_ids)

    def create_onss_declaration(self):
        if self.filtered(lambda d: d.declaration_method != 'batch'):
            raise UserError(self.env._("DmfA Declaration type should be via batch"))
        return super().create_onss_declaration()

    def action_download_declaration_file(self):
        self.ensure_one()
        if self.declaration_method == 'web' and self.dmfa_pdf:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/l10n_be.dmfa/{self.id}/dmfa_pdf/{self.dmfa_pdf_filename}?download=true',
                'target': 'self',
            }
        if self.declaration_method == 'batch':
            return super().action_download_declaration_file()
        raise UserError(self.env._("No file available to download. Please generate the XML or PDF report first."))

    @api.depends('year', 'quarter')
    def _compute_eligible_payslip_ids(self):
        payslips_by_dmfa = {}
        warrant_structure = self.env.ref('l10n_be_hr_payroll.hr_payroll_structure_cp200_structure_warrant')
        valid_structure_type = self.env.ref('hr.structure_type_employee_cp200')
        quarter_start = min(dmfa.quarter_start for dmfa in self)
        quarter_end = max(dmfa.quarter_end for dmfa in self)
        payslips_domain = [
            '|',
                '&', ('date_to', '>=', quarter_start), ('date_to', '<=', quarter_end),
                # A termination indemnity is dated at the start of the notice period, before or after the end of
                # the contract
                '&', '&', ('struct_id.code', '=', 'BETERM'),
                    ('date_to', '>=', quarter_start - relativedelta(years=2)),
                    ('date_to', '<=', quarter_end + relativedelta(months=1)),
            ('state', 'in', ['validated', 'paid']),
            ('company_id', 'in', self.branch_ids.ids),
        ]

        def _get_quarter_date(payslip):
            # A termination indemnity is declared in the quarter of the end of the contract
            if payslip.struct_id.code == 'BETERM' and payslip.version_id.contract_date_end:
                return payslip.version_id.contract_date_end
            return payslip.date_to

        payslips = self.env['hr.payslip'].search(payslips_domain, order='date_to desc, id')
        for dmfa in self:
            # Exclude CIP contracts from DmfA, as they only have a DIMONA
            if dmfa.state in ('done', 'paid', 'pending', 'in_progress'):
                payslips_by_dmfa[dmfa.id] = payslips.filtered(lambda p: (p.l10n_be_dmfa_id == dmfa.id))
            else:
                payslips_by_dmfa[dmfa.id] = payslips.filtered(lambda p: (
                        dmfa.quarter_start <= _get_quarter_date(p) <= dmfa.quarter_end
                        and p.company_id in dmfa.branch_ids._origin
                        and p.version_id.l10n_be_worker_code_id.dmfa_code not in ['000', '848', '849']
                        # not subject to the ONSS (article 17, occasional workers in agriculture, internships...)
                        and not p.version_id.no_onss
                        and p.version_id.structure_type_id == valid_structure_type
                        and p.version_id.l10n_be_joint_committee_id.egov3_code != '999'
                        and not p.l10n_be_is_dmfa_reported
                        and (p.struct_id != warrant_structure or p._get_input_line_amount('WARRANT_WITH_ONSS'))
                ))
            dmfa.payslip_ids = payslips_by_dmfa[dmfa.id]
        return payslips_by_dmfa

    @api.depends('payslip_ids')
    def _compute_first_hires_reductions_eligible_employee_ids(self):
        for dmfa in self:
            payslips = dmfa.payslip_ids
            versions = payslips.version_id
            eligible_versions = versions.filtered(lambda v: v.l10n_be_dimona_category not in ['stu', 'flx'])
            dmfa.first_hires_reductions_eligible_employee_ids = eligible_versions.mapped('employee_id')

    @api.depends('payslip_ids')
    def _compute_payslip_count(self):
        for dmfa in self:
            dmfa.payslip_count = len(dmfa.with_context(active_test=False).payslip_ids)

    def action_show_related_payslips(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Related Payslips"),
            "res_model": "hr.payslip",
            "view_mode": "list,form",
            "domain": [('id', 'in', self.with_context(active_test=False).payslip_ids.ids)],
            "context": {
                "dmfa_id": self.id,
                "active_test": False,
                "dialog_size": "extra-large",
            },
            "target": "current",
        }

    def action_reset_to_draft(self):
        res = super().action_reset_to_draft()
        self.dmfa_pdf = None
        return res

    def action_mark_done(self):
        res = super().action_mark_done()
        self.payslip_ids.l10n_be_is_dmfa_reported = True
        if self.declaration_type == 'modification' and self.declaration_method == 'web':
            self.parent_id.is_correction_needed = False
        return res

    def action_mark_paid(self):
        self.ensure_one()
        if not self.name:
            raise ValidationError(_("Please provide the reference to mark the report as paid"))
        self.state = 'paid'

    def action_create_consultation_request(self):
        self.ensure_one()
        consultation_request_values = {
            'year': self.year,
            'quarter': self.quarter,
            'company_id': self.company_id.id,
            'parent_id': self.id,
            'name': self.name,
            'environment': self.environment,
            'declaration_method': self.declaration_method,
            'correction_reason': self.correction_reason,
            'declaration_type': 'consultation',
        }
        consultation_request = self.env['l10n_be.dmfa'].sudo().create(consultation_request_values)
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_id': consultation_request.id,
            'res_model': 'l10n_be.dmfa',
            'target': 'current',
        }

    def action_create_modification_request(self):
        self.ensure_one()
        modification_request_values = {
            'year': self.year,
            'quarter': self.quarter,
            'company_id': self.company_id.id,
            'parent_id': self.parent_id.id,
            'name': self.parent_id.name,
            'environment': self.environment,
            'declaration_method': self.declaration_method,
            'correction_reason': self.correction_reason,
            'declaration_type': 'modification',
        }
        modification_request = self.env['l10n_be.dmfa'].sudo().create(modification_request_values)
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_id': modification_request.id,
            'res_model': 'l10n_be.dmfa',
            'target': 'current',
        }

    def action_correct_web_dmfa(self):
        self.ensure_one()
        if self.has_unfinished_modification:
            for child in self.children_ids:
                if child.state not in ('done', 'refused'):
                    return {
                        'type': 'ir.actions.act_window',
                        'view_mode': 'form',
                        'res_id': child.id,
                        'res_model': 'l10n_be.dmfa',
                        'target': 'current',
                    }
        self.is_correction_needed = False
        modification_dmfa_values = {
            'year': self.year,
            'quarter': self.quarter,
            'company_id': self.company_id.id,
            'parent_id': self.id,
            'name': self.parent_id.name,
            'declaration_method': self.declaration_method,
            'correction_reason': self.correction_reason,
            'declaration_type': 'modification',
        }
        modification_dmfa = self.env['l10n_be.dmfa'].sudo().create(modification_dmfa_values)
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_id': modification_dmfa.id,
            'res_model': 'l10n_be.dmfa',
            'target': 'current',
        }

    def _generate_artist_reduction_lines(self, natural_persons):
        entries = defaultdict(float)  # (employee_id, code) : amount
        for natural_person in natural_persons:
            for worker_record in natural_person.worker_records:
                for occupation in worker_record.occupations:
                    for deduction in occupation.occupation_deductions or []:
                        if not isinstance(deduction, DMFAOccupationTargetGroup) or deduction.deduction_code != 4300:
                            continue
                        amount = int(deduction.deduction_amount) / 100.0
                        entries[deduction.employee.id, deduction.deduction_code] += amount
        if not entries:
            return

        self.write({
            "artist_reduction_line_ids": [(5, 0, 0)] + [(0, 0, {
                'employee_id': employee_id,
                'deduction_code': code,
                'amount': amount,
            }) for (employee_id, code), amount in entries.items()]
        })

    @api.depends('state')
    def _compute_issues(self):
        self.issues = {}
        if (
            (not self.env.registry.ready or config["test_enable"] or modules.module.current_test)
            # This context key acts as an escape hatch for upgrade scripts that need to
            # explicitly recompute payroll issues while the registry is still initializing,
            # and for the tests that check the issues.
            and not (self.env.context.get("hr_payroll_force_compute_issue"))
        ):
            return

        dmfa_warnings = self.env["hr.payroll.warning"].search([
            ("display_on_model", "=", True),
            ("model_name", "=", "l10n_be.dmfa"),
            ("active", "=", True),
        ])

        for dmfa in self:

            warning_result = {}
            for warning in dmfa_warnings:
                if warning.warning_type == 'domain':
                    warning_result[warning] = (warning._get_warning_domain_records(dmfa.company_id, records_to_check=dmfa), {})
                else:
                    records, details, additional_context, context = warning._get_warning_python_records(localdict={'active_ids': dmfa.id})
                    if records:
                        warning_result[warning] = (records, details or {}, additional_context or {}, context or {})

            dmfa_issues = []

            for warning, (rec, details, add_context, context) in warning_result.items():
                if warning.warning_type == 'python' and details:
                    issue = details
                else:
                    issue = warning._get_warning_issue()

                dmfa_issues.append(issue)

            dmfa.issues = dict(enumerate(dmfa_issues)) if dmfa_issues else {}

    def _generate_elderly_reduction_lines(self, natural_persons):
        elderly_codes = {int(code) for code in self.env['hr.payslip']._l10n_be_elderly_reduction_codes()}
        entries = defaultdict(float)  # (employee_id,code) -> amount
        for natural_person in natural_persons:
            for worker_record in natural_person.worker_records:
                for occupation in worker_record.occupations:
                    for deduction in occupation.occupation_deductions or []:
                        if not isinstance(deduction, DMFAOccupationTargetGroup) or deduction.deduction_code not in elderly_codes:
                            continue
                        amount = int(deduction.deduction_amount) / 100.0
                        entries[deduction.employee.id, deduction.deduction_code] += amount
        if not entries:
            return

        self.write({
            "elderly_reduction_line_ids": [(5, 0, 0)] + [(0, 0, {
                'employee_id': employee_id,
                'deduction_code': code,
                'amount': amount,
            }) for (employee_id, code), amount in entries.items()]
        })

    def _generate_unexperienced_reduction_lines(self, natural_persons):
        """Refresh the stored 6340 reduction lines from the rendered natural persons.
        date_from/date_to span the full active window of the current cycle:
        from the first active quarter (position 0) to the last (position 3).
        """
        self.ensure_one()
        self.unexperienced_reduction_line_ids.unlink()
        lines = []
        for np in natural_persons:
            for worker in np.worker_records:
                for occupation in worker.occupations:
                    for deduction in occupation.occupation_deductions or []:
                        if not isinstance(deduction, DMFAOccupationTargetGroup) or deduction.deduction_code not in [6340]:
                            continue
                        employee = np.employee
                        window = self._get_unexperienced_reduction_cycle_window(employee, self.quarter_start)
                        if not window:
                            continue
                        window_start, window_end = window
                        lines.append({
                            'dmfa_id': self.id,
                            'employee_id': np.employee.id,
                            'date_from': window_start,
                            'date_to': window_end,
                            'amount': int(deduction.deduction_amount) / 100.0,
                        })
        self.env['l10n_be.dmfa.unexperienced.reduction'].create(lines)

    def _generate_acs_deduction_lines(self, natural_persons):
        entries = defaultdict(float)
        for natural_person in natural_persons:
            for worker_record in natural_person.worker_records:
                for occupation in worker_record.occupations:
                    for deduction in occupation.occupation_deductions or []:
                        if not isinstance(deduction, DMFAOccupationTargetGroup) or deduction.deduction_code not in [4000, 4001]:
                            continue
                        amount = int(deduction.deduction_amount) / 100.0
                        entries[deduction.employee.id, deduction.deduction_code] += amount
        if not entries:
            return
        self.write({
            "acs_deduction_line_ids": [(5, 0, 0)] + [(0, 0, {
                'employee_id': employee_id,
                'deduction_code': code,
                'amount': amount,
            }) for (employee_id, code), amount in entries.items()]
        })

    def _get_unexperienced_reduction_cycle_window(self, employee, reference_date):
        def _quarter_start(d):
            return date_utils.get_quarter(d)[0]

        def _quarter_end(d):
            return date_utils.get_quarter(d)[1]

        def _next_quarter(d):
            return _quarter_start(_quarter_end(d) + relativedelta(days=1))

        def _quarter_diff(q1, q2):
            return (q1.year - q2.year) * 4 + (q1.month - q2.month) // 3

        current_quarter = _quarter_start(reference_date)

        all_versions = employee.sudo().version_ids.filtered(
            lambda v: v.contract_date_start).sorted('date_version')

        contract_end_by_start = {}
        for version in all_versions:
            contract_end_by_start[version.contract_date_start] = version.contract_date_end

        active_quarters = set()
        for contract_start, contract_end in contract_end_by_start.items():
            c_start_q = _quarter_start(contract_start)
            c_end_q = _quarter_start(contract_end) if contract_end else current_quarter
            q = c_start_q
            while _quarter_diff(current_quarter, q) >= 0:
                active_quarters.add(q)
                if _quarter_diff(c_end_q, q) <= 0:
                    break
                q = _next_quarter(q)

        sorted_active = sorted(active_quarters)
        if not sorted_active:
            return None

        cycle_start_idx = 0
        for i in range(1, len(sorted_active)):
            gap = _quarter_diff(sorted_active[i], sorted_active[i - 1]) - 1
            if gap >= 4:
                cycle_start_idx = i

        cycle_quarter = sorted_active[cycle_start_idx]
        if not cycle_quarter:
            return None

        window_start = cycle_quarter
        window_end = _quarter_end(_next_quarter(_next_quarter(_next_quarter(cycle_quarter))))
        return window_start, window_end


class L10nBeDmfaElderlyReductionLine(models.Model):
    _name = 'l10n_be.dmfa.elderly.reduction.line'
    _description = 'DMFA Elderly Reduction Line'

    dmfa_id = fields.Many2one('l10n_be.dmfa', required=True, ondelete='cascade', index='btree_not_null')
    company_id = fields.Many2one(related='dmfa_id.company_id', store=True, index='btree_not_null')
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict')
    deduction_code = fields.Char(string="Code")
    amount = fields.Monetary(currency_field='currency_id')


class L10nBeDmfaArtistReductionLine(models.Model):
    _name = 'l10n_be.dmfa.artist.reduction.line'
    _description = 'DmfA Artist Reduction Line'

    dmfa_id = fields.Many2one('l10n_be.dmfa', required=True, ondelete='cascade', index='btree_not_null')
    company_id = fields.Many2one(related='dmfa_id.company_id', store=True, index='btree_not_null')
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict')
    deduction_code = fields.Char(string="Code")
    amount = fields.Monetary(currency_field='currency_id')


class DMFANaturalPersonState(models.Model):
    _name = 'l10n_be.dmfa.natural_person.state'
    _description = 'DMFA Natural Person State'

    employee_id = fields.Many2one('hr.employee', string='Employee', index=True)
    niss = fields.Char(string='NISS')
    quarter_start = fields.Date(string='Quarter Start')
    quarter_end = fields.Date(string='Quarter End')
    natural_person_pid = fields.Char(string='Natural Person PID')
    decl_natural_person_pid = fields.Char(string='Declaration Natural Person PID')
    occupation_version_map = fields.Json(string='Occupation Version Map', default={})

    worker_record_version_number = fields.Char(string='Worker Record Version Number')
    worker_record_data = fields.Json(default={})
    modification_justification = fields.Char(string="Justification")

    version_number = fields.Char(string='Version Number')

    def update_occupation_version(self, occupation_id, version_id, changed=False):
        self.ensure_one()
        if isinstance(occupation_id, int):
            occupation_id = str(occupation_id)
        if isinstance(version_id, int):
            version_id = str(version_id)
        version_map = self.occupation_version_map or {}
        if occupation_id not in version_map:
            version_map[occupation_id] = version_id.zfill(11)
        elif changed:
            version_map[occupation_id] = (str(int(version_id) + 1)).zfill(11)
        self.occupation_version_map = version_map

    def validate_changes(self, checked_data, worker_code):
        self.ensure_one()
        if worker_code not in self.worker_record_data:
            self.worker_record_data[worker_code] = checked_data
            self.worker_record_data[worker_code]['update_action'] = 3
            self.version_number = str(int(self.version_number) + 1)
            return
        if self.worker_record_data[worker_code] != checked_data:
            self.worker_record_data[worker_code] = checked_data
            self.worker_record_data[worker_code]['update_action'] = 1
            self.version_number = str(int(self.version_number) + 1)
        else:
            self.worker_record_data[worker_code]['update_action'] = 9


class DMFAEmployeesWizard(models.TransientModel):
    _name = 'l10n_be.dmfa.employees.wizard'
    _description = 'Employees for DMFA Wizard'

    dmfa_id = fields.Many2one('l10n_be.dmfa')
    select_all = fields.Boolean(string="Fetch All Employees", default=True)
    employee_ids = fields.Many2many('hr.employee', string="Specific Employees", domain="[('company_id', 'in', allowed_company_ids)]")

    def action_confirm_selection(self):
        self.ensure_one()
        self.dmfa_id = self.env.context.get('default_dmfa_id')
        employees_to_process = None
        if not self.select_all:
            employees_to_process = self.employee_ids
        self.dmfa_id.with_context(employees_to_report=employees_to_process).generate_declaration_xml_report()
        return {'type': 'ir.actions.act_window_close'}


class L10nBeDmfaUnexperiencedReduction(models.Model):
    _name = 'l10n_be.dmfa.unexperienced.reduction'
    _description = 'DMFA Unexperienced Employee Reduction (Code 6340)'
    _order = 'employee_id'

    dmfa_id = fields.Many2one('l10n_be.dmfa', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True, string='Employee')
    date_from = fields.Date(string='Start Date')
    date_to = fields.Date(string='End Date')
    amount = fields.Float(string='Amount', digits=(10, 2))


class L10nBeDmfaACSReductionLine(models.Model):
    _name = 'l10n_be.dmfa.acs.reduction.line'
    _description = 'DMFA ACS Reduction Line'

    dmfa_id = fields.Many2one('l10n_be.dmfa', required=True, ondelete='cascade', index='btree_not_null')
    company_id = fields.Many2one(related='dmfa_id.company_id', store=True, index='btree_not_null')
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict')
    deduction_code = fields.Char(string="Code")
    amount = fields.Monetary(string="Deduction", currency_field='currency_id',
        help="Total amount of the deduction for this employee in this quarter.")
