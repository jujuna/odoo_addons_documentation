from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, format_date, formatLang

from .tools import gec_lock_for_update

UNIT_COMPONENTS = ('unit_basic', 'unit_extra')
DAILY_COMPONENTS = ('daily_basic', 'worklog_daily')


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # Salary-line order, followed by the header card and tooltips.
    _GEC_COMPONENT_RULE_CODE = {
        'daily_basic': 'DAILY_BASIC',
        'timesheet_basic': 'TIMESHEET_BASIC',
        'unit_basic': 'UNIT_BASIC',
        'worklog_ot': 'WORKLOG_OT',
        'worklog_daily': 'WORKLOG_DAILY',
        'timesheet_extra': 'TIMESHEET_EXTRA',
        'unit_extra': 'UNIT_EXTRA',
    }
    _GEC_UNCLAIMED_LOG_DOMAIN = [('state', '=', 'approved'), ('settlement_ids', 'not any', [('active_claim', '=', True)])]
    _GEC_UNCLAIMED_TIMESHEET_DOMAIN = [
        ('project_id', '!=', False),
        ('work_log_id', '=', False),
        ('gec_payroll_waived_at', '=', False),
        ('gec_settlement_ids', 'not any', [('active_claim', '=', True)]),
    ]

    gec_settlement_ids = fields.One2many('hr.payroll.component.settlement', 'payslip_id')

    gec_settlement_count = fields.Integer(string='Work Logs and Timesheets', compute='_compute_gec_settlement_count', compute_sudo=True)

    gec_work_item_amount = fields.Monetary(string='Work Logs and Timesheets Amount', compute='_compute_gec_work_item_summary', compute_sudo=True)

    gec_work_item_summary = fields.Char(string='Work Logs and Timesheets Summary', compute='_compute_gec_work_item_summary', compute_sudo=True)

    @api.depends('gec_settlement_ids.active_claim')
    def _compute_gec_settlement_count(self):
        for payslip in self:
            payslip.gec_settlement_count = len(payslip.gec_settlement_ids.filtered('active_claim'))

    @api.depends('gec_settlement_ids.active_claim')
    def _compute_gec_work_item_summary(self):
        """Corrections and refunds hold no claims and show no card."""
        labels = dict(self.env['hr.payroll.component.settlement']._fields['component_code']._description_selection(self.env))
        for payslip in self:
            settlements = payslip.gec_settlement_ids.filtered('active_claim')
            parts = []
            for code in self._GEC_COMPONENT_RULE_CODE:
                component = settlements.filtered(lambda s: s.component_code == code)
                if component:
                    parts.append(self.env._("%(quantity)s %(component)s", quantity=payslip._gec_quantity_text(component), component=labels[code]))
            payslip.gec_work_item_amount = sum(settlements.mapped('amount'))
            payslip.gec_work_item_summary = " · ".join(parts)

    def _gec_struct_pays(self, component_code):
        self.ensure_one()
        rule_code = self._GEC_COMPONENT_RULE_CODE.get(component_code)
        return bool(rule_code) and bool(self.struct_id.rule_ids.filtered(lambda r: r.code == rule_code))

    def _gec_in_claim_scope(self):
        """Only regular salary and overtime originals can own work items."""
        self.ensure_one()
        return (
            self.state == 'draft'
            and not self.credit_note
            and not self.origin_payslip_id
            and bool(self.version_id)
            and (self._gec_is_overtime() or (
                self.is_regular
                and self.struct_id == self.version_id.structure_type_id.default_struct_id))
        )

    def _gec_can_claim(self):
        self.ensure_one()
        return self._gec_in_claim_scope() and not self.edited

    def _gec_claim_window(self):
        """Window: the contract's part of the period; starts at the contract only when an earlier contract overlaps."""
        self.ensure_one()
        if self._gec_is_overtime():
            # An overtime slip may settle older approved work, even of a former employee.
            return False, self.date_to
        version = self.version_id.sudo()
        window_end = self.date_to
        if version.contract_date_end and version.contract_date_end < window_end:
            window_end = version.contract_date_end
        window_start = False
        if version.contract_date_start and version.contract_date_start > self.date_from:
            earlier_contracts = self.employee_id.sudo().version_ids.filtered(
                lambda v: v.contract_date_start
                and v.contract_date_start < version.contract_date_start
                and (not v.contract_date_end or v.contract_date_end >= self.date_from))
            if earlier_contracts:
                window_start = version.contract_date_start
        return window_start, window_end

    def _gec_claim_window_domain(self):
        self.ensure_one()
        window_start, window_end = self._gec_claim_window()
        domain = [('employee_id', '=', self.employee_id.id), ('company_id', '=', self.company_id.id), ('date', '<=', window_end)]
        if window_start:
            domain.append(('date', '>=', window_start))
        return domain

    def _gec_candidate_domain(self):
        return [*self._gec_claim_window_domain(), *self._GEC_UNCLAIMED_LOG_DOMAIN]

    def _gec_log_component_code(self, log):
        if log.component_code_snapshot:
            return log.component_code_snapshot
        return log._resolve_component_code(log.version_id)

    def _gec_log_payable(self, log):
        code = self._gec_log_component_code(log)
        overtime_slip = self._gec_is_overtime()
        if code == 'worklog_ot':
            separate = log.version_id.sudo().overtime_pay_mode == 'separate'
            if separate != overtime_slip:
                return False
        elif overtime_slip:
            return False
        if not code or not self._gec_struct_pays(code):
            return False
        if log.currency_id_snapshot and log.currency_id_snapshot != self.company_id.currency_id:
            return False
        return True

    def _gec_claimable_slips(self):
        return self.filtered(lambda slip: slip._gec_can_claim()).sorted(key=lambda s: (s.employee_id.id, s.date_to, s.id))

    def _gec_claim_work_logs(self):
        log_model = self.env['hr.employee.work.log'].sudo()
        settlement_model = self.env['hr.payroll.component.settlement']
        for slip in self._gec_claimable_slips():
            logs = log_model.search(slip._gec_candidate_domain()).filtered(slip._gec_log_payable)
            if not logs:
                continue
            gec_lock_for_update(logs)
            logs.invalidate_recordset(['settlement_ids', 'state'])
            vals_list = []
            for log in logs:
                if log.state != 'approved' or log.settlement_ids.filtered('active_claim'):
                    continue
                code = slip._gec_log_component_code(log)
                if not slip._gec_log_payable(log):
                    continue
                vals_list.append({
                    'work_log_id': log.id,
                    'payslip_id': slip.id,
                    'payslip_ref': slip.name or '',
                    'employee_id': log.employee_id.id,
                    'company_id': log.company_id.id,
                    'currency_id': (log.currency_id_snapshot or log.currency_id).id,
                    'component_code': code,
                    'source_version_id': log.version_id.id,
                    'date': log.date,
                    'quantity': log.hours if log.type == 'overtime' else (log.unit_qty if log.type == 'unit' else log.units),
                    'uom_id': log.unit_uom_snapshot_id.id,
                    'rate': log.rate_snapshot,
                    'amount': log.amount_snapshot,
                })
            settlement_model.create(vals_list)

    def _gec_check_claims(self):
        """Drafts only: core's run Validate passes already validated slips again."""
        for slip in self.filtered(lambda slip: slip.state == 'draft'):
            settlements = slip.gec_settlement_ids.filtered('active_claim')
            broken = settlements.filtered(lambda settlement: not slip._gec_settlement_still_valid(settlement))
            if broken:
                raise UserError(self.env._("Payslip %(slip)s pays work logs or timesheets that changed after it was computed: compute the payslip "
                    "again first.", slip=slip.name))

    def _gec_unclaimed_slips(self):
        """Two searches for all payslips; each payslip then keeps what falls in its own claim window."""
        slips = self.filtered(lambda slip: slip._gec_in_claim_scope())
        if not slips:
            return slips
        scope = [('employee_id', 'in', slips.employee_id.ids), ('company_id', 'in', slips.company_id.ids), ('date', '<=', max(slips.mapped('date_to')))]
        logs = self.env['hr.employee.work.log'].sudo().search([*scope, *self._GEC_UNCLAIMED_LOG_DOMAIN])
        lines = self.env['account.analytic.line'].sudo().search([*scope, *self._GEC_UNCLAIMED_TIMESHEET_DOMAIN])
        logs_by_employee, lines_by_employee = logs.grouped('employee_id'), lines.grouped('employee_id')

        def has_unclaimed_work(slip):
            window, employee = slip._gec_claim_window_domain(), slip.employee_id
            return (logs_by_employee.get(employee, logs.browse()).filtered_domain(window).filtered(slip._gec_log_payable)
                or lines_by_employee.get(employee, lines.browse()).filtered_domain(window).filtered(slip._gec_timesheet_payable))
        return slips.filtered(has_unclaimed_work)

    def _gec_check_lines_match_settlements(self):
        for slip in self:
            if not (slip._gec_is_regular_base() or slip._gec_is_overtime_base()):
                continue
            for component_code, rule_code in self._GEC_COMPONENT_RULE_CODE.items():
                expected = slip.gec_component_total(component_code)
                actual = sum(slip.line_ids.filtered(lambda l: l.code == rule_code).mapped('total'))
                if slip.company_id.currency_id.compare_amounts(actual, expected) != 0:
                    raise UserError(self.env._("Payslip %(slip)s line %(code)s (%(actual).2f) does not match its work logs and timesheets "
                        "(%(expected).2f): compute the payslip again before validating.", slip=slip.name, code=rule_code, actual=actual,
                        expected=expected))

    def _gec_has_schedule_base(self):
        self.ensure_one()
        currency = self.company_id.currency_id
        worked_day_base = sum(self.worked_days_line_ids.mapped('amount'))
        basic_line_total = sum(self.line_ids.filtered(lambda line: line.code == 'BASIC').mapped('total'))
        return (currency.compare_amounts(worked_day_base, 0.0) != 0 or currency.compare_amounts(basic_line_total, 0.0) != 0)

    def _gec_schedule_base_slips(self):
        return self.filtered(lambda slip: slip._gec_is_regular_base() and slip.wage_type in ('daily', 'unit') and slip._gec_has_schedule_base())

    def _gec_timesheet_base_slips(self):
        """Timesheet-mode slips pay only settlements, with a zero work-entry base."""
        basic_category = self.env.ref('hr_payroll.BASIC')
        broken = self.browse()
        for slip in self.filtered(lambda slip: slip._gec_is_regular_base() and slip.gec_uses_timesheet_hourly_base()):
            rules = slip.struct_id.rule_ids.filtered(lambda r: r.code == 'TIMESHEET_BASIC')
            if (slip.edited or slip.struct_id != slip.version_id.sudo().structure_type_id.default_struct_id or not rules
                    or any(rule.category_ids != basic_category for rule in rules) or slip._gec_has_schedule_base()):
                broken |= slip
        return broken

    def _gec_component_settlements(self, component_code):
        self.ensure_one()
        return self._benefit_root_origin().gec_settlement_ids.filtered(lambda s: s.active_claim and s.component_code == component_code)

    def gec_component_total(self, component_code):
        """Component total from the chain root's claims."""
        self.ensure_one()
        sign = -1 if self.credit_note else 1
        return sign * sum(self._gec_component_settlements(component_code).mapped('amount'))

    def gec_component_line_vals(self, component_code):
        """(amount, quantity) of a component line: unrounded unit value x claimed total equals the settlement."""
        self.ensure_one()
        total = self.gec_component_total(component_code)
        quantity = sum(self._gec_component_settlements(component_code).mapped('quantity'))
        if float_compare(quantity, 0.0, precision_digits=4) <= 0:
            return total, 1.0
        return total / quantity, quantity

    def _gec_quantity_text(self, settlements):
        code = settlements[:1].component_code
        if code in UNIT_COMPONENTS:
            by_uom = defaultdict(float)
            for settlement in settlements:
                by_uom[settlement.uom_id] += settlement.quantity
            return ", ".join(f"{formatLang(self.env, quantity)} {uom.name or ''}".rstrip() for uom, quantity in by_uom.items())
        quantity = formatLang(self.env, sum(settlements.mapped('quantity')))
        if code in DAILY_COMPONENTS:
            return self.env._("%(quantity)s days", quantity=quantity)
        return self.env._("%(quantity)s h", quantity=quantity)

    def gec_component_explanation(self, component_code):
        """Tooltip of a work-item line, called from the rules."""
        self.ensure_one()
        settlements = self._gec_component_settlements(component_code)
        if not settlements:
            return {'explanation': ''}
        count = len(settlements)
        if component_code in DAILY_COMPONENTS:
            source = self.env._("%(count)s approved Daily Work logs", count=count)
        elif component_code == 'worklog_ot':
            source = self.env._("%(count)s approved Overtime logs", count=count)
        elif component_code in UNIT_COMPONENTS:
            source = self.env._("%(count)s approved Unit Work logs", count=count)
        else:
            source = self.env._("%(count)s timesheet lines", count=count)
        dates = sorted(settlements.mapped('date'))
        period = format_date(self.env, dates[0])
        if dates[-1] != dates[0]:
            period = f"{period} - {format_date(self.env, dates[-1])}"
        if component_code in UNIT_COMPONENTS:
            items = defaultdict(float)
            for settlement in settlements:
                key = (settlement.work_log_id.work_unit_id.name or '', settlement.uom_id.name or '', settlement.rate)
                items[key] += settlement.quantity
            detail = ", ".join(
                f"{name} {formatLang(self.env, quantity)} {uom} × {self._gec_money(rate)}"
                for (name, uom, rate), quantity in items.items())
        elif component_code == 'worklog_ot':
            # The frozen rate is the plain hourly wage; the log's Rate % is added on top.
            groups = defaultdict(lambda: self.env['hr.payroll.component.settlement'])
            for settlement in settlements:
                groups[(settlement.rate, settlement.work_log_id.percentage)] |= settlement
            detail = " + ".join(
                f"{self._gec_quantity_text(lines)} × {self._gec_money(rate)} × {percentage}%"
                for (rate, percentage), lines in groups.items())
        else:
            quantity = self._gec_quantity_text(settlements)
            rates = set(settlements.mapped('rate'))
            if len(rates) == 1:
                detail = f"{quantity} × {self._gec_money(rates.pop())}"
            else:
                detail = self.env._("%(quantity)s at %(count)s different rates", quantity=quantity, count=len(rates))
        text = self.env._("%(records)s (%(period)s): %(detail)s = %(total)s", records=source, period=period, detail=detail,
            total=self._gec_money(self.gec_component_total(component_code)))
        if component_code in ('timesheet_basic', 'timesheet_extra'):
            by_project = defaultdict(lambda: self.env['hr.payroll.component.settlement'])
            for settlement in settlements:
                by_project[settlement.timesheet_line_id.project_id] |= settlement
            projects = ", ".join(f"{project.display_name} {self._gec_quantity_text(lines)}" for project, lines in by_project.items() if project)
            if projects:
                text = self.env._("%(text)s. Projects: %(projects)s", text=text, projects=projects)
        return {'explanation': text}

    def _recompute_with_forced_lines(self, forced_line_vals):
        """Core re-forces untouched lines from rounded values, breaking the settlement check."""
        if self.state != 'draft':
            return super()._recompute_with_forced_lines(forced_line_vals)
        work_item_codes = set(self._GEC_COMPONENT_RULE_CODE.values())
        forced = {line.code: {
            'name': line.name,
            'amount': line.total,
            'quantity': 1.0,
            'rate': 100.0,
        } for line in self.line_ids if line.code in work_item_codes}
        forced.update(forced_line_vals)
        # Core also forces, with their stored amounts, all lines before the first forced one.
        first_forced = min(self.line_ids.filtered(lambda line: line.code in forced).mapped('sequence'), default=0)
        kept = {
            line.code: line.explanation for line in self.line_ids
            if line.explanation and line.code not in forced_line_vals
            and (line.code in forced or line.sequence < first_forced)
        }
        res = super()._recompute_with_forced_lines(forced)
        for line in self.line_ids:
            if line.code in kept:
                line.explanation = kept[line.code]
            elif line.code in forced_line_vals and line.salary_rule_id.explanation_template:
                line.explanation = False
        return res

    def action_open_gec_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Work Logs and Timesheets'),
            'res_model': 'hr.payroll.component.settlement',
            'view_mode': 'list,form',
            'domain': [('payslip_id', '=', self.id)],
            'context': {'search_default_live_claims': 1, 'search_default_group_component': 1},
        }

    def gec_uses_timesheet_hourly_base(self):
        self.ensure_one()
        version = self.version_id.sudo()
        return bool(version) and version._gec_uses_timesheet_hourly_base()

    def _gec_timesheet_candidate_domain(self):
        """Unclaimed, unwaived project timesheets in the claim window; overtime mirrors never count."""
        return [*self._gec_claim_window_domain(), *self._GEC_UNCLAIMED_TIMESHEET_DOMAIN]

    def _gec_timesheet_payable(self, line):
        if self._gec_is_overtime():
            return False
        version = self.employee_id.sudo()._get_version(line.date)
        if not version:
            return False
        code = version._gec_timesheet_component_code()
        if not code or not self._gec_struct_pays(code):
            return False
        return version._gec_timesheet_line_eligible(line)

    def _gec_check_timesheet_day_caps(self, lines):
        self.ensure_one()
        if not lines:
            return
        settlement_model = self.env['hr.payroll.component.settlement']
        hours_by_date = defaultdict(float)
        for line in lines:
            hours_by_date[line.date] += line.unit_amount
        claimed = settlement_model.search([
            ('employee_id', '=', self.employee_id.id),
            ('active_claim', '=', True),
            ('timesheet_line_id', '!=', False),
            ('date', 'in', list(hours_by_date)),
        ])
        for settlement in claimed:
            hours_by_date[settlement.date] += settlement.quantity
        for day, total in hours_by_date.items():
            if float_compare(total, 24.0, precision_digits=2) > 0:
                raise UserError(self.env._("%(employee)s has %(total).2f payable timesheet hours on %(date)s, over the 24h/day limit. Fix or delete "
                    "the excess lines before computing payroll.", employee=self.employee_id.name, total=total, date=day))

    def _gec_claim_timesheets(self):
        """Claim eligible timesheets for regular draft slips; validation is not needed."""
        line_model = self.env['account.analytic.line'].sudo()
        settlement_model = self.env['hr.payroll.component.settlement']
        for slip in self._gec_claimable_slips():
            lines = line_model.search(slip._gec_timesheet_candidate_domain()).filtered(slip._gec_timesheet_payable)
            if not lines:
                continue
            gec_lock_for_update(lines)
            lines.invalidate_recordset()
            employee = slip.employee_id.sudo()
            currency = slip.company_id.currency_id
            lines = lines.filtered(slip._gec_timesheet_payable).filtered(lambda line: not line.gec_settlement_ids.filtered('active_claim'))
            slip._gec_check_timesheet_day_caps(lines)
            vals_list = []
            for line in lines:
                version = employee._get_version(line.date)
                vals_list.append({
                    'timesheet_line_id': line.id,
                    'payslip_id': slip.id,
                    'payslip_ref': slip.name or '',
                    'employee_id': slip.employee_id.id,
                    'company_id': slip.company_id.id,
                    'currency_id': currency.id,
                    'component_code': version._gec_timesheet_component_code(),
                    'source_version_id': version.id,
                    'date': line.date,
                    'quantity': line.unit_amount,
                    'rate': version.hourly_wage,
                    'amount': currency.round(line.unit_amount * version.hourly_wage),
                })
            settlement_model.create(vals_list)

    def _gec_settlement_still_valid(self, settlement):
        """Compute releases failing claims; edited slips keep theirs as they can never re-claim."""
        self.ensure_one()
        if not self._gec_in_claim_scope():
            return False
        window_start, window_end = self._gec_claim_window()
        if (settlement.employee_id != self.employee_id
                or settlement.company_id != self.company_id
                or settlement.date > window_end
                or (window_start and settlement.date < window_start)):
            return False
        if settlement.work_log_id:
            log = settlement.work_log_id
            return (log.state == 'approved'
                    and self._gec_log_payable(log)
                    and settlement.component_code == self._gec_log_component_code(log)
                    and settlement.currency_id.compare_amounts(settlement.amount, log.amount_snapshot) == 0)
        if settlement.timesheet_line_id:
            line = settlement.timesheet_line_id
            if not self._gec_timesheet_payable(line):
                return False
            version = self.employee_id.sudo()._get_version(line.date)
            expected = self.company_id.currency_id.round(line.unit_amount * version.hourly_wage)
            return (settlement.source_version_id == version
                    and settlement.component_code == version._gec_timesheet_component_code()
                    and settlement.currency_id.compare_amounts(settlement.amount, expected) == 0)
        return False

    def _gec_release_stale_claims(self):
        settlement_model = self.env['hr.payroll.component.settlement']
        stale = settlement_model
        for slip in self:
            for settlement in slip.gec_settlement_ids.filtered('active_claim'):
                if not slip._gec_settlement_still_valid(settlement):
                    stale |= settlement
        if stale:
            stale._release(self.env._('Payslip recomputed'))
            settlement_model.flush_model(['active_claim'])

    @api.ondelete(at_uninstall=False)
    def _gec_release_settlements(self):
        self.gec_settlement_ids.filtered('active_claim')._release(self.env._('Payslip deleted'))
