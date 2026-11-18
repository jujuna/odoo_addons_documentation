# Part of Odoo. See LICENSE file for full copyright and licensing details.

import collections
from io import BytesIO

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes
from odoo.tools.misc import format_date

# The reasons of the end of the contracts (code of the departure reason), by reason of the social balance sheet:
# pension (340), unemployment with company supplement (341), dismissal (342), another reason (343)
# Source: CNC S100, 3.7.4 (https://www.nbb.be/doc/ba/models/social%20balance/avis_cnc_s100.pdf)
DEPARTURE_REASON_CODES = {
    340: 340,  # Retired
    354: 340,  # Anticipated retirement
    341: 341,
    353: 341,  # Fired: early retirement
    342: 342,  # Fired
    355: 342,  # Fired: serious misconduct
    358: 342,  # Fired: notice by the employer
    359: 342,  # Fired: termination by the employer
}

# The totals of the previous exercise in the model (P. column): the average number of workers in FTE, the hours
# actually worked, the personnel costs and the benefits granted in addition to the wages
PREVIOUS_EXERCISE_CODES = ('1003', '1013', '1023', '1033')


class L10nBeSocialBalanceSheet(models.TransientModel):
    _name = 'l10n.be.social.balance.sheet'
    _description = 'Belgium: Social Balance Sheet'

    @api.model
    def default_get(self, fields):
        if self.env.company.country_id.code != "BE":
            raise UserError(self.env._('This feature seems to be as exclusive as Belgian chocolates. You must be logged in to a Belgian company to use it.'))
        return super().default_get(fields)

    def _get_default_company_id(self):
        return self.env.company if not self.env.company.parent_id else False

    # Source: https://www.nbb.be/fr/centrale-des-bilans/etablir-et-deposer/que-faut-il-deposer/modeles/modeles-pour-societes
    # Introduction: https://www.nbb.be/doc/ba/models/social%20balance/avis_cnc_2009_12.pdf
    # Q&A about social balance sheet: https://www.nbb.be/doc/ba/models/social%20balance/avis_cnc_s100.pdf
    # Explanations about trainings: https://www.nbb.be/doc/ba/models/social%20balance/avis_cnc_2009_12.pdf
    # Blank complete scheme example: https://www.nbb.be/doc/ba/models/ent/2023/standaardmodellen/release_2021_fr_modele_c_societes_a_capital_v8.pdf

    date_from = fields.Date(default=lambda s: fields.Date.context_today(s) + relativedelta(day=1, month=1, years=-1))
    date_to = fields.Date(default=lambda s: fields.Date.context_today(s) + relativedelta(day=31, month=12, years=-1))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')
    social_balance_sheet = fields.Binary('Social Balance Sheet', readonly=True, attachment=False)
    company_id = fields.Many2one(
        "res.company",
        domain="[('parent_id', '=', False)]",
        default=_get_default_company_id,
        required=True,
    )
    branch_ids = fields.Many2many("res.company", compute="_compute_branch_ids")
    social_balance_filename = fields.Char()

    @api.depends('company_id')
    def _compute_branch_ids(self):
        report_companies = self.mapped('company_id')
        branches_by_root = self.env['res.company'].search([
            ('id', 'child_of', report_companies.ids),
        ]).grouped('root_id')

        for report in self:
            report.branch_ids = branches_by_root.get(report.company_id, report.company_id)

    def _get_report_data(self):
        def _get_contract_type_code(contract, replacement, defined_work):
            if contract.employee_type_id == replacement:
                return '113'
            if contract.employee_type_id == defined_work:
                return '112'
            if contract.fixed_term:
                return '111'  # CDD
            return '110'  # CDI

        def _get_in_out_contract_type_code(contract, replacement, defined_work):
            if contract.employee_type_id == replacement:
                return '213', '313'
            if contract.employee_type_id == defined_work:
                return '212', '312'
            if contract.fixed_term:
                return '211', '311'  # CDD
            return '210', '310'  # CDI

        def _get_category_code(version):
            # The apprentices, interns and trainees are in the other workers (133), the students are with the manual
            # workers (132) or the employees (134) according to their status (CNC S100, 2.1.2.2 and 3.5)
            if version.l10n_be_dimona_category in ('alt', 'rta', 'stg', 'ivt', 'tri'):
                return '133'
            dmfa_code = version.l10n_be_worker_code_id.dmfa_code or ''
            return '132' if dmfa_code.startswith('0') or dmfa_code == '840' else '134'

        self.ensure_one()
        report_data = {}

        payslips = self.env['hr.payslip'].search([
            ('state', 'in', ['validated', 'paid']),
            ('struct_id.type_id', '=', self.env.ref('hr.structure_type_employee_cp200').id),
            ('company_id', 'in', self.branch_ids.ids),
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
            ('version_id.l10n_be_worker_code_id.dmfa_code', 'not in', ['848', '849']),
            # the company directors (joint committee 999) have no employment contract
            ('version_id.l10n_be_joint_committee_id.egov3_code', '!=', '999'),
            ])
        # SECTION 100
        # The average of the number of workers in the register at the end of each month of the period, the
        # suspended workers included and the workers who left during the month excluded (CNC S100, 3.1.3)
        employees = self.env['hr.employee'].with_context(active_test=False).search([('company_id', 'in', self.branch_ids.ids)])
        month_versions = []
        month_end = self.date_from + relativedelta(day=31)
        while month_end <= self.date_to:
            versions = employees._get_versions_with_contract_overlap_with_period(month_end, month_end).filtered(lambda v: (
                v.company_id in self.branch_ids
                and v.l10n_be_worker_code_id.dmfa_code not in ['848', '849']
                and v.l10n_be_joint_committee_id.egov3_code != '999'
            ))
            month_versions.append(versions)
            month_end = month_end + relativedelta(days=1) + relativedelta(day=31)

        invalid_employees = (payslips.version_id | self.env['hr.version'].union(month_versions)).filtered(
            lambda v: v.sex not in ['male', 'female']).employee_id
        if invalid_employees:
            raise UserError(self.env._('Please configure a sex (either male or female) for the following employees:\n\n%s', '\n'.join(invalid_employees.mapped('name'))))

        workers_data = collections.defaultdict(lambda: dict(full=0, part=0, fte=0))
        for versions in month_versions:
            for version in versions:
                sex = version.sex
                if version.work_time_rate >= 1:
                    workers_data[sex]['full'] += 1
                    workers_data[sex]['fte'] += 1
                else:
                    workers_data[sex]['part'] += 1
                    workers_data[sex]['fte'] += 1 * version.work_time_rate
        month_count = len(month_versions) or 1

        report_data.update({
            '1001_male': round(workers_data['male']['full'] / month_count, 2),
            '1001_female': round(workers_data['female']['full'] / month_count, 2),
            '1001_total': round((workers_data['male']['full'] + workers_data['female']['full']) / month_count, 2),
            '1002_male': round(workers_data['male']['part'] / month_count, 2),
            '1002_female': round(workers_data['female']['part'] / month_count, 2),
            '1002_total': round((workers_data['male']['part'] + workers_data['female']['part']) / month_count, 2),
            '1003_male': round(workers_data['male']['fte'] / month_count, 2),
            '1003_female': round(workers_data['female']['fte'] / month_count, 2),
            '1003_total': round((workers_data['male']['fte'] + workers_data['female']['fte']) / month_count, 2),
        })

        # SECTION 101
        # The methodological notice concerning the social report published in the Belgian Official
        # Gazette (Moniteur belge) of August 30, 1996 specifies that the actual number of hours
        # worked (item 101) includes: "the total hours actually worked performed and paid during
        # the year; that is to say without take into account unpaid overtime (62), vacation, sick
        # leave, absences of short duration (63) and hours lost due to strike or for any other
        # reason ”.
        # This definition is directly followed by the description of what is meant by number of
        # hours worked on the basis of the quarterly declaration to the ONSS. This way to proceed
        # may lead to an overestimation of the hours of work actually performed. Indeed, the
        # ONSS takes into account the hours or days not worked but assimilated (64) to working days
        # to determine the employee benefits.
        workers_data = collections.defaultdict(lambda: dict(full=0, part=0, fte=0))
        working_time_types = self.env['hr.work.entry.type'].search([
            ('count_as', '=', 'working_time'),
            ('country_id.code', '=', 'BE'),
        ])
        for payslip in payslips:
            version = payslip.version_id
            sex = version.sex
            worked_paid_hours = sum(
                line.number_of_hours for line in payslip.worked_days_line_ids
                if line.is_paid and line.work_entry_type_id in working_time_types
            )
            if not worked_paid_hours:
                continue
            if version.work_time_rate >= 1:
                workers_data[sex]['full'] += worked_paid_hours
                workers_data[sex]['fte'] += worked_paid_hours
            else:
                workers_data[sex]['part'] += worked_paid_hours
                workers_data[sex]['fte'] += worked_paid_hours
        report_data.update({
            '1011_male': round(workers_data['male']['full'], 2),
            '1011_female': round(workers_data['female']['full'], 2),
            '1011_total': round((workers_data['male']['full'] + workers_data['female']['full']), 2),
            '1012_male': round(workers_data['male']['part'], 2),
            '1012_female': round(workers_data['female']['part'], 2),
            '1012_total': round((workers_data['male']['part'] + workers_data['female']['part']), 2),
            '1013_male': round(workers_data['male']['fte'], 2),
            '1013_female': round(workers_data['female']['fte'], 2),
            '1013_total': round((workers_data['male']['fte'] + workers_data['female']['fte']), 2),
        })

        # SECTION 102 - 103: Staff Costs
        # Must be mentioned under heading 102 - "Expenses of personnel" charges which by reason of
        # their nature are entered under heading 62 of the minimum chart of accounts standardized,
        # provided that these loads concern workers covered by the social report (see above). Are
        # therefore included under the above heading, in so far as they concern the workers in
        # question:
        # - direct compensation and social benefits;
        # - employer's social contributions;
        # - employer premiums for extra-legal insurance;
        # - other personnel costs.
        # The remuneration is the gross one, before the worker social contributions and without the taxable benefits in
        # kind, which aren't personnel costs (S100, 3.3.1.2). The meal vouchers paid by the employer are personnel costs
        # (account 623), the private car allowance is already in the gross.
        workers_data = collections.defaultdict(lambda: collections.defaultdict(lambda: dict(full=0, part=0)))
        Rule = self.env['hr.salary.rule'].with_context(active_test=False)
        worker_onss_codes = set(Rule.search([('category_ids', 'in', self.env.ref('l10n_be_hr_payroll.ONSS').ids)]).mapped('code'))
        benefit_in_kind_codes = set(Rule.search([
            ('category_ids', 'in', self.env.ref('l10n_be_hr_payroll.BIK').ids),
            ('category_ids', 'in', self.env.ref('l10n_be_hr_payroll.WITHHOLDING_BASE').ids),
        ]).mapped('code'))
        gross_codes = self.env['hr.payslip']._get_gross_wage_line_codes()
        expense_codes = ['ONSSEMPLOYER', 'PUB.TRANS', 'TRAIN', 'REP.FEES']
        line_values = payslips._get_line_values(
            [*gross_codes, *worker_onss_codes, *benefit_in_kind_codes, *expense_codes, 'MEAL_V_EMP', 'IP.PART'],
            vals_list=['total', 'quantity'])
        for payslip in payslips:
            sex = payslip.version_id.sex
            contract_type = 'full' if payslip.version_id.work_time_rate >= 1 else 'part'

            def total(codes, payslip=payslip):
                return sum(line_values[code][payslip.id]['total'] for code in codes)

            # The copyright part (IP.PART, negative) is paid as well
            gross = total(gross_codes) - total(worker_onss_codes) - total(benefit_in_kind_codes) - total(['IP.PART'])
            meal_vouchers = payslip.version_id.meal_voucher_paid_by_employer * line_values['MEAL_V_EMP'][payslip.id]['quantity']
            workers_data['total'][sex][contract_type] += round(gross + total(expense_codes) + meal_vouchers, 2)
        # The benefits granted in addition to the wages, which aren't personnel costs
        meal_voucher = dict(male=0, female=0)

        report_data['102'] = workers_data
        report_data['103'] = meal_voucher

        # SECTION 105-113, 120, 121, 130-134: At the end of the exercice
        workers_data = collections.defaultdict(lambda: dict(full=0, part=0, fte=0))

        end_contracts = self.env['hr.employee'].search([
            ('company_id', 'in', self.branch_ids.ids),
        ])._get_versions_with_contract_overlap_with_period(self.date_to, self.date_to)
        end_contracts = end_contracts.filtered(lambda c: c.company_id in self.branch_ids)
        paid_employees = {employee for [employee] in self.env['hr.payslip']._read_group(
            [('employee_id', 'in', end_contracts.employee_id.ids), ('state', 'in', ['validated', 'paid'])],
            ['employee_id'],
        )}
        end_contracts = end_contracts.filtered(lambda c: (
            c.l10n_be_worker_code_id.dmfa_code not in ['848', '849']
            and c.l10n_be_joint_committee_id.egov3_code != '999'
            and c.employee_id in paid_employees
        ))
        end_contracts_by_employees = collections.defaultdict(lambda: self.env['hr.version'])
        last_end_contracts = self.env['hr.version']
        for end_contract in end_contracts:
            end_contracts_by_employees[end_contract.employee_id] += end_contract
        for employee_contracts in end_contracts_by_employees.values():
            last_end_contracts += employee_contracts.sorted('date_version', reverse=True)[0]
        end_contracts = last_end_contracts

        replacement = self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_replacement')
        # not created anymore, only exists on older databases
        defined_work = self.env.ref('l10n_be_hr_payroll.l10n_be_contract_type_clearly_defined_work', raise_if_not_found=False)

        mapped_certificates = {
            ('male', 'graduate'): '1202',
            ('male', 'bachelor'): '1202',
            ('male', 'master'): '1203',
            ('male', 'doctor'): '1203',
            ('male', 'other'): '1201',
            ('male', False): '1201',
            ('male', 'civil_engineer'): '1203',
            ('male', 'primary'): '1200',
            ('male', 'lower_secondary'): '1201',
            ('male', 'higher_secondary'): '1201',
            ('female', 'graduate'): '1212',
            ('female', 'bachelor'): '1212',
            ('female', 'master'): '1213',
            ('female', 'doctor'): '1213',
            ('female', 'other'): '1211',
            ('female', False): '1211',
            ('female', 'civil_engineer'): '1213',
            ('female', 'primary'): '1210',
            ('female', 'lower_secondary'): '1211',
            ('female', 'higher_secondary'): '1211',
        }

        for contract in end_contracts:
            contract_type = _get_contract_type_code(contract, replacement, defined_work)
            sex = contract.employee_id.sex
            work_time_rate = contract.work_time_rate

            contract_time = 'full' if work_time_rate >= 1 else 'part'

            workers_data['105'][contract_time] += 1
            workers_data['105']['fte'] += 1 * work_time_rate

            workers_data[contract_type][contract_time] += 1
            workers_data[contract_type]['fte'] += 1 * work_time_rate

            if (sex, contract.employee_id.certificate) not in mapped_certificates:
                raise UserError(self.env._("The employee %(employee)s doesn't have a supported sex and certificate level (%(sex)s, %(certificate)s).", employee=contract.employee_id.name, sex=sex, certificate=contract.employee_id.certificate))
            sex_code = '120' if sex == 'male' else '121'
            workers_data[sex_code][contract_time] += 1
            workers_data[sex_code]['fte'] += 1 * work_time_rate
            sex_certificate_code = mapped_certificates[sex, contract.employee_id.certificate]
            workers_data[sex_certificate_code][contract_time] += 1
            workers_data[sex_certificate_code]['fte'] += 1 * work_time_rate

            category_code = _get_category_code(contract)
            workers_data[category_code][contract_time] += 1
            workers_data[category_code]['fte'] += 1 * work_time_rate

        for code in [
                '105', '110', '111', '112', '113',
                '120', '1200', '1201', '1202', '1203',
                '121', '1210', '1211', '1212', '1213',
                '130', '132', '133', '134']:
            report_data[code] = workers_data[code]

        # SECTION 200: Staff Movements (Entries / Departure)
        # Each contract starting or ending in the period, a worker hired again being counted again. A contract following
        # another one without interruption (renewal, fixed term to permanent contract) is neither an entry nor a
        # departure. The entry is declared with the situation at the start of the contract, the departure with the
        # situation at its end (CNC S100, 3.7).
        workers_data = collections.defaultdict(lambda: dict(full=0, part=0, fte=0))

        contracts = employees.version_ids.filtered(lambda v: (
            v.contract_date_start
            and v.company_id in self.branch_ids
            and v.l10n_be_worker_code_id.dmfa_code not in ['848', '849']
            and v.l10n_be_joint_committee_id.egov3_code != '999'
        )).grouped(lambda v: (v.employee_id, v.contract_date_start, v.contract_date_end))
        contract_starts = collections.defaultdict(set)
        contract_ends = collections.defaultdict(set)
        for employee, date_start, date_end in contracts:
            contract_starts[employee].add(date_start)
            contract_ends[employee].add(date_end)
        one_day = relativedelta(days=1)

        def _add(code, version):
            work_time_rate = version.work_time_rate
            workers_data[code]['full' if work_time_rate >= 1 else 'part'] += 1
            workers_data[code]['fte'] += 1 * work_time_rate

        for (employee, date_start, date_end), versions in contracts.items():
            versions = versions.sorted('date_version')
            if self.date_from <= date_start <= self.date_to and date_start - one_day not in contract_ends[employee]:
                version = versions[0]
                _add('205', version)
                _add(_get_in_out_contract_type_code(version, replacement, defined_work)[0], version)
            if date_end and self.date_from <= date_end <= self.date_to and date_end + one_day not in contract_starts[employee]:
                version = versions[-1]
                _add('305', version)
                _add(_get_in_out_contract_type_code(version, replacement, defined_work)[1], version)
                # The reason of the departure of the employee, for the last contract
                last_contract = all(start <= date_start for start in contract_starts[employee])
                employee_reason_code = employee.departure_reason_id.l10n_be_reason_code if last_contract else False
                reason_code = str(DEPARTURE_REASON_CODES.get(employee_reason_code, 343))
                _add(reason_code, version)
                if employee_reason_code == 350:
                    # Of which the workers who keep working for the company as self-employed
                    _add('350', version)

        for code in [
                '205', '210', '211', '212', '213',
                '305', '310', '311', '312', '313',
                '340', '341', '342', '343', '350']:
            report_data[code] = workers_data[code]

        # SECTION 580: Trainings
        for code in ['5821', '5831', '5822', '5832', '5823', '5833', '5841', '5851', '5842', '5852', '5843',
            '5853', '58033', '58133', '5801', '5811', '5802', '5812', '58031', '58131', '58032', '58132',
            '5803', '5813']:
            report_data[code] = 0

        # The joint committees of the workers
        report_data['joint_committees'] = sorted(set(filter(None, (
            payslips.version_id | self.env['hr.version'].union(month_versions)
        ).l10n_be_joint_committee_id.mapped('egov3_code'))))

        report_data['year'] = self.date_from.strftime('%Y')

        # The same period of the previous exercise, for the totals to compare with
        if not self.env.context.get('l10n_be_social_balance_previous_exercise'):
            previous_sheet = self.with_context(l10n_be_social_balance_previous_exercise=True).create({
                'company_id': self.company_id.id,
                'date_from': self.date_from - relativedelta(years=1),
                'date_to': self.date_to - relativedelta(years=1),
            })
            try:
                previous_data = previous_sheet._get_report_data()
            except UserError:
                # Workers of the previous exercise without sex: its totals are left to be completed by hand rather than
                # blocking the report of the exercise
                report_data['previous_exercise'] = {}
            else:
                [(_title, _columns, lines), *_sections] = previous_sheet._get_report_sections(previous_data)
                report_data['previous_exercise'] = {code: values[0] for code, _label, values in lines if code in PREVIOUS_EXERCISE_CODES}

        return report_data

    def print_report(self):
        report_data = self._get_report_data()
        filename = self.env._(
            'SocialBalance-%(date_from)s-%(date_to)s.pdf',
            date_from=format_date(self.env, self.date_from),
            date_to=format_date(self.env, self.date_to))
        export_social_balance_sheet_pdf, _ = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
            self.env.ref('l10n_be_hr_payroll.action_report_social_balance').id,
            res_ids=self.ids, data={'sbs_data': report_data})

        self.social_balance_filename = filename
        self.social_balance_sheet = BinaryBytes(export_social_balance_sheet_pdf)
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Social Balance Sheet'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _get_report_sections(self, data):
        """ The tables of the social balance sheet, as in the model of the National Bank of Belgium

        :return: [(title, column titles, [(code, label, values)])]
        """
        def by_sex(code):
            return [data[f'{code}_total'], data[f'{code}_male'], data[f'{code}_female']]

        def with_previous_exercise(lines):
            # The total of the previous exercise, for the codes of the model which have one
            previous_exercise = data.get('previous_exercise', {})
            return [(code, label, [*values, previous_exercise.get(code)]) for code, label, values in lines]

        def costs(*contract_times):
            # The amounts are in euros, without cents
            male = sum(data['102']['total']['male'][time] for time in contract_times)
            female = sum(data['102']['total']['female'][time] for time in contract_times)
            return [round(male + female), round(male), round(female)]

        def by_time(code):
            return [data[code]['full'], data[code]['part'], data[code]['fte']]

        sex_columns = [self.env._('Total'), self.env._('Male'), self.env._('Female')]
        time_columns = [self.env._('Full time'), self.env._('Part time'), self.env._('Total in FTE')]
        contract_types = [
            self.env._('Permanent contract (CDI)'),
            self.env._('Fixed term contract (CDD)'),
            self.env._('Contract for the execution of a clearly defined work'),
            self.env._('Replacement contract'),
        ]
        education_levels = [
            self.env._('Primary education'),
            self.env._('Secondary education'),
            self.env._('Non-university higher education'),
            self.env._('University education'),
        ]
        return [
            (self.env._('During the exercise'), [*sex_columns, self.env._('Previous exercise: total')], with_previous_exercise([
                ('1001', self.env._('Average number of workers: full time'), by_sex('1001')),
                ('1002', self.env._('Average number of workers: part time'), by_sex('1002')),
                ('1003', self.env._('Average number of workers: total in FTE'), by_sex('1003')),
                ('1011', self.env._('Number of hours actually worked: full time'), by_sex('1011')),
                ('1012', self.env._('Number of hours actually worked: part time'), by_sex('1012')),
                ('1013', self.env._('Number of hours actually worked: total'), by_sex('1013')),
                ('1021', self.env._('Personnel costs: full time'), costs('full')),
                ('1022', self.env._('Personnel costs: part time'), costs('part')),
                ('1023', self.env._('Personnel costs: total'), costs('full', 'part')),
                ('1033', self.env._('Amount of the benefits granted in addition to the wages'),
                    [round(data['103']['male'] + data['103']['female']), round(data['103']['male']), round(data['103']['female'])]),
            ])),
            (self.env._('At the closing date of the exercise'), time_columns, [
                ('105', self.env._('Number of workers'), by_time('105')),
                *((code, label, by_time(code)) for code, label in zip(['110', '111', '112', '113'], contract_types)),
                ('120', self.env._('Male'), by_time('120')),
                *((code, label, by_time(code)) for code, label in zip(['1200', '1201', '1202', '1203'], education_levels)),
                ('121', self.env._('Female'), by_time('121')),
                *((code, label, by_time(code)) for code, label in zip(['1210', '1211', '1212', '1213'], education_levels)),
                ('130', self.env._('Management staff'), by_time('130')),
                ('134', self.env._('Employees'), by_time('134')),
                ('132', self.env._('Workers'), by_time('132')),
                ('133', self.env._('Others'), by_time('133')),
            ]),
            (self.env._('Entries'), time_columns, [
                ('205', self.env._('Number of workers'), by_time('205')),
                *((code, label, by_time(code)) for code, label in zip(['210', '211', '212', '213'], contract_types)),
            ]),
            (self.env._('Departures'), time_columns, [
                ('305', self.env._('Number of workers'), by_time('305')),
                *((code, label, by_time(code)) for code, label in zip(['310', '311', '312', '313'], contract_types)),
                ('340', self.env._('Pension'), by_time('340')),
                ('341', self.env._('Unemployment with company supplement'), by_time('341')),
                ('342', self.env._('Dismissal'), by_time('342')),
                ('343', self.env._('Another reason'), by_time('343')),
                ('350', self.env._('Of which: the number of persons who continue to provide services to the company at least half-time as self-employed'), by_time('350')),
            ]),
            # Not known by the payroll: to be completed by hand
            (self.env._('Temporary staff and personnel made available to the company'), [
                self.env._('Temporary staff'), self.env._('Personnel made available to the company'),
            ], [
                ('150', self.env._('Average number of occupied persons'), [None, None]),
                ('151', self.env._('Number of hours effectively worked'), [None, None]),
                ('152', self.env._('Cost for the company'), [None, None]),
            ]),
            *((title, [self.env._('Male'), self.env._('Female')], [
                (f'{male_code} / {female_code}', label, [None, None]) for male_code, female_code, label in lines
            ]) for title, lines in [
                (self.env._("Formal continuous trainings at the employer's expense"), [
                    ('5801', '5811', self.env._('Number of affected workers')),
                    ('5802', '5812', self.env._('Number of completed training hours')),
                    ('5803', '5813', self.env._('Net cost for the company')),
                    ('58031', '58131', self.env._('Gross cost directly linked to training')),
                    ('58032', '58132', self.env._('Contributions paid and payments to collective funds')),
                    ('58033', '58133', self.env._('Grants and other financial benefits received (to be deducted)')),
                ]),
                (self.env._("Informal continuous trainings at the employer's expense"), [
                    ('5821', '5831', self.env._('Number of affected workers')),
                    ('5822', '5832', self.env._('Number of completed training hours')),
                    ('5823', '5833', self.env._('Net cost for the company')),
                ]),
                (self.env._("Initial trainings at the employer's expense"), [
                    ('5841', '5851', self.env._('Number of affected workers')),
                    ('5842', '5852', self.env._('Number of completed training hours')),
                    ('5843', '5853', self.env._('Net cost for the company')),
                ]),
            ]),
        ]

    def export_report_xlsx(self):
        """ Download the social balance sheet as a spreadsheet (see :meth:`_get_xlsx_file`) """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/l10n_be_hr_payroll/social_balance_sheet/{self.id}/xlsx',
            'target': 'download',
        }

    def _get_xlsx_file(self):
        """ Return the social balance sheet as a spreadsheet, to be used by the softwares of the annual accounts.

        :return: the file name and the content of the file
        :rtype: tuple[str, bytes]
        """
        self.ensure_one()
        report_data = self._get_report_data()
        output = BytesIO()
        import xlsxwriter  # noqa: PLC0415
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(self.env._('Social Balance Sheet'))
        style_title = workbook.add_format({'bold': True, 'font_size': 14})
        style_header = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#E0E0E0', 'bottom': 1})
        style_bold = workbook.add_format({'bold': True})
        style_number = workbook.add_format({'num_format': '#,##0.00'})
        style_integer = workbook.add_format({'num_format': '#,##0'})
        worksheet.set_column(0, 0, 10)
        worksheet.set_column(1, 1, 80)
        worksheet.set_column(2, 5, 18)

        worksheet.write(0, 0, self.env._('Social Balance Sheet - Complete Scheme'), style_title)
        payroll_config = self.company_id._get_payroll_config(self.date_from)
        identification = [
            (self.env._('Company'), self.company_id.name),
            (self.env._('Company Number'), payroll_config.l10n_be_company_number or self.company_id.vat or ''),
            (self.env._('ONSS Number'), payroll_config.onss_registration_number or ''),
            (self.env._('Numbers of joint committees'), ', '.join(report_data['joint_committees'])),
            (self.env._('Period'), '%s - %s' % (format_date(self.env, self.date_from), format_date(self.env, self.date_to))),
            (self.env._('Currency'), self.company_id.currency_id.name),
        ]
        row = 2
        for label, value in identification:
            worksheet.write(row, 1, label, style_bold)
            worksheet.write(row, 2, value)
            row += 1

        for title, columns, lines in self._get_report_sections(report_data):
            row += 1
            worksheet.write_row(row, 0, [self.env._('Code'), title, *columns], style_header)
            for code, label, values in lines:
                row += 1
                worksheet.write(row, 0, code)
                worksheet.write(row, 1, label)
                for column, value in enumerate(values, start=2):
                    if value is None:
                        continue
                    # The numbers of workers and the amounts in euros are integers
                    worksheet.write_number(row, column, round(value, 2), style_integer if isinstance(value, int) else style_number)
            row += 1

        workbook.close()
        filename = self.env._(
            'SocialBalance-%(date_from)s-%(date_to)s.xlsx',
            date_from=format_date(self.env, self.date_from),
            date_to=format_date(self.env, self.date_to))
        return filename, output.getvalue()

    def action_validate(self):
        self.ensure_one()
        if self.social_balance_sheet:
            self._post_process_generated_file(self.social_balance_sheet, self.social_balance_filename)
        xlsx_filename, xlsx_content = self._get_xlsx_file()
        self._post_process_generated_file(xlsx_content, xlsx_filename)
        return {'type': 'ir.actions.act_window_close'}

    # To be overwritten in documents_l10n_be_hr_payroll to create a document.document
    def _post_process_generated_file(self, data, filename):
        return
