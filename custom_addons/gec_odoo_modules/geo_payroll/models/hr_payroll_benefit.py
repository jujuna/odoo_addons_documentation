from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

BENEFIT_LOCKED_FIELDS = frozenset({'partner_id', 'advance', 'payslip_count', 'employee_amount', 'company_amount'})


class HrPayrollBenefit(models.Model):
    _name = 'hr.payroll.benefit'
    _inherit = ['mail.thread']
    _description = 'Benefit / Deduction Program'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Vendor', tracking=True, check_company=True,
        help="Who this benefit is paid to, for example the gym. Pay Salaries transfers both the employee share and the company share to this vendor. "
        "The company share is then not paid to the employee in cash: income tax and pension apply to it as to salary.")
    company_amount = fields.Monetary(tracking=True,
        help="Cash amount the company pays to the employee per period (bonus). With a Vendor it is paid to the vendor instead.")
    employee_amount = fields.Monetary(tracking=True, help="Amount deducted from the employee's net salary per period.")
    recurrence = fields.Selection([('once', 'One Time'), ('monthly', 'Monthly')], default='once', required=True, tracking=True)
    pay_mode = fields.Selection([('with_salary', 'With Salary'), ('separate', 'Separate Payment')], default='with_salary', required=True,
        tracking=True,
        help="Separate Payment pays only the company amount, on a benefits payslip of its own; amounts taken from the employee need With Salary. "
        "For a salary advance this sets where the advance is paid out (the next salary payslip or a benefits payslip); the repayments are always "
        "taken from the following salary payslips.")
    advance = fields.Boolean(string='Salary Advance', tracking=True,
        help="Tick for a salary advance: it is paid out once, taxed when paid out, and then repaid from the next salary payslips without being "
        "taxed again.")
    payslip_count = fields.Integer(string='Repaid Over (Payslips)', default=1, tracking=True,
        help="Number of next salary payslips the advance repayment is spread over.")
    date_from = fields.Date(string='From', required=True, tracking=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', tracking=True)
    note = fields.Text(string='Conditions')
    line_ids = fields.One2many('hr.payroll.benefit.line', 'benefit_id')
    employee_count = fields.Integer(compute='_compute_employee_count')
    locked = fields.Boolean(compute='_compute_locked')

    _check_amounts = models.Constraint('CHECK (company_amount >= 0 AND employee_amount >= 0)', 'Benefit amounts cannot be negative.')

    @api.depends('line_ids')
    def _compute_employee_count(self):
        for benefit in self:
            benefit.employee_count = len(benefit.line_ids)

    def _compute_locked(self):
        for benefit in self:
            benefit.locked = bool(benefit._all_lines()._locked_payslip_inputs())

    def action_open_assign(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Add Employees'),
            'res_model': 'hr.payroll.benefit.assign',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_benefit_id': self.id},
        }

    def _all_lines(self):
        return self.with_context(active_test=False).line_ids

    @api.model_create_multi
    def create(self, vals_list):
        benefits = super().create(vals_list)
        benefits._all_lines()._touch_draft_payslips()
        return benefits

    def write(self, vals):
        locked_vals = vals.keys() & BENEFIT_LOCKED_FIELDS
        # not benefit.locked: it has no dependencies, so a value cached earlier in the transaction would be stale
        blocked = self.filtered(lambda benefit: (locked_vals if benefit.advance else locked_vals & {'partner_id', 'advance'})
            and benefit._all_lines()._locked_payslip_inputs())
        if blocked:
            raise UserError(self.env._("%(names)s already paid on validated payslips: the vendor and the advance terms cannot change. "
                "Archive the program and create a new one.", names=', '.join(blocked.mapped('name'))))
        res = super().write(vals)
        self._all_lines()._touch_draft_payslips()
        return res

    def unlink(self):
        slips = self._all_lines()._draft_slips()
        res = super().unlink()
        slips._benefit_refresh()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_paid_lines(self):
        lines = self._all_lines()
        if lines.filtered('payslip_id') or lines._locked_payslip_inputs():
            raise UserError(self.env._('This benefit was already paid on a payslip and cannot be deleted. Archive it instead.'))


class HrPayrollBenefitLine(models.Model):
    _name = 'hr.payroll.benefit.line'
    _description = 'Benefit Employee Line'
    _rec_name = 'employee_id'
    _check_company_auto = True

    benefit_id = fields.Many2one('hr.payroll.benefit', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='benefit_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='benefit_id.currency_id')
    employee_id = fields.Many2one('hr.employee', required=True, index=True, check_company=True)
    company_amount = fields.Monetary()
    employee_amount = fields.Monetary()
    date_from = fields.Date(string='From', help='Overrides the program start for this employee.')
    date_to = fields.Date(string='To', help='Overrides the program end for this employee.')
    payslip_id = fields.Many2one('hr.payslip', string='Paid By', copy=False, readonly=True, index='btree_not_null', ondelete='set null',
        check_company=True)
    payslip_ids = fields.Many2many('hr.payslip', string='Payslips', compute='_compute_payslip_ids',
        help="Payslips carrying the pay-out or an installment of this advance.")
    active = fields.Boolean(default=True)
    state = fields.Selection([('pending', 'Pending'), ('done', 'Paid'), ('running', 'Running'), ('expired', 'Expired')], string='Status',
        compute='_compute_state')

    _check_amounts = models.Constraint('CHECK (company_amount >= 0 AND employee_amount >= 0)', 'Benefit amounts cannot be negative.')
    _one_active_per_employee = models.UniqueIndex('(benefit_id, employee_id) WHERE active')

    @api.depends('payslip_id', 'date_to', 'benefit_id.recurrence', 'benefit_id.date_to', 'benefit_id.advance', 'benefit_id.payslip_count')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        saved_advances = self.filtered(lambda line: line.benefit_id.advance and line.payslip_id and isinstance(line.id, int))
        repaid_by_line = Counter(
            inp.benefit_line_id.id for inp in saved_advances._advance_carrier_inputs()
            if inp.payslip_id.state in ('validated', 'paid'))
        for line in self:
            if line.benefit_id.advance:
                if not line.payslip_id:
                    line.state = 'pending'
                    continue
                if line in saved_advances:
                    repaid = repaid_by_line[line.id]
                else:
                    repaid = len([inp for inp in line._advance_carrier_inputs() if inp.payslip_id.state in ('validated', 'paid')])
                done = repaid >= max(line.benefit_id.payslip_count, 1)
                line.state = 'done' if done else 'running'
            elif line.benefit_id.recurrence == 'once':
                line.state = 'done' if line.payslip_id else 'pending'
            else:
                end = line.date_to or line.benefit_id.date_to
                line.state = 'expired' if end and end < today else 'running'

    def _compute_payslip_ids(self):
        real_ids = [line_id for line_id in self.ids if isinstance(line_id, int)]
        inputs = self.env['hr.payslip.input'].sudo().search([
            ('benefit_line_id', 'in', real_ids),
            ('payslip_id.state', '!=', 'cancel'),
            ('payslip_id.credit_note', '=', False),
        ]) if real_ids else self.env['hr.payslip.input']
        for line in self:
            line.payslip_ids = inputs.filtered(lambda inp: inp.benefit_line_id == line).payslip_id

    def _in_period(self, date_start, date_end, payslip=None):
        """A line stamped by `payslip` stays eligible for it, so a reset slip re-injects its own benefit."""
        self.ensure_one()
        benefit = self.benefit_id
        start = self.date_from or benefit.date_from
        end = self.date_to or benefit.date_to
        if benefit.advance:
            # Repayments run from the start date until the payslip count is used up.
            return not start or start <= date_end
        if benefit.recurrence == 'once':
            consumed = self.payslip_id and self.payslip_id != payslip
            return not consumed and (not start or start <= date_end)
        return bool(start) and start <= date_end and (not end or end >= date_start)

    def _advance_total(self):
        """A line paid out before amounts were stored per line keeps the program total."""
        self.ensure_one()
        return self.employee_amount or (self.benefit_id.employee_amount if self.payslip_id else 0.0)

    def _advance_carrier_inputs(self, exclude_payslip=None):
        """Live ADVANCE (repayment) inputs of these advance lines, one per correction chain."""
        if not self:
            return []
        domain = [
            ('benefit_line_id', 'in', self.ids),
            ('salary_rule_id.code', '=', 'ADVANCE'),
            ('payslip_id.state', '!=', 'cancel'),
            ('payslip_id.credit_note', '=', False),
        ]
        if exclude_payslip:
            domain.append(('payslip_id', '!=', exclude_payslip.id))
        inputs = self.env['hr.payslip.input'].sudo().search(domain)
        by_chain = {}
        for line_input in inputs:
            root = line_input.payslip_id._benefit_root_origin()
            if not root._gec_is_regular_base():
                continue
            by_chain.setdefault((line_input.benefit_line_id.id, root.id), line_input)
        return list(by_chain.values())

    def _advance_slip_amount(self, payslip):
        """Installment from the remaining amount, so the total repays exactly after edits or deletions."""
        self.ensure_one()
        others = self._advance_carrier_inputs(exclude_payslip=payslip)
        slips_left = max(self.benefit_id.payslip_count, 1) - len(others)
        remaining = self._advance_total() - sum(inp.amount for inp in others)
        if slips_left <= 0 or self.currency_id.compare_amounts(remaining, 0.0) <= 0:
            return 0.0
        if slips_left == 1:
            return remaining
        return self.currency_id.round(remaining / slips_left)

    def _locked_payslip_inputs(self):
        """Inputs on validated or paid payslips that use these lines; the cascade must not reach them."""
        if not self:
            return self.env['hr.payslip.input']
        return self.env['hr.payslip.input'].sudo().search([('benefit_line_id', 'in', self.ids), ('payslip_id.state', 'in', ('validated', 'paid'))])

    def _draft_slips(self):
        if not self.employee_id:
            return self.env['hr.payslip']
        return self.env['hr.payslip'].search([('state', '=', 'draft'), ('edited', '=', False), ('employee_id', 'in', self.employee_id.ids)])

    def _touch_draft_payslips(self):
        self._draft_slips()._benefit_refresh()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            benefit = self.env['hr.payroll.benefit'].browse(vals.get('benefit_id'))
            if benefit.advance and 'employee_amount' not in vals:
                vals['employee_amount'] = benefit.employee_amount
        lines = super().create(vals_list)
        lines._touch_draft_payslips()
        return lines

    def write(self, vals):
        paid = self.filtered(lambda line: line.payslip_id and line.benefit_id.advance)
        if paid and vals.keys() & {'employee_amount', 'company_amount'}:
            raise UserError(self.env._("The advance of %(names)s was already paid out; its amount cannot change.",
                names=', '.join(paid.employee_id.mapped('name'))))
        slips = self._draft_slips()
        res = super().write(vals)
        slips |= self._draft_slips()
        slips._benefit_refresh()
        return res

    def unlink(self):
        slips = self._draft_slips()
        res = super().unlink()
        slips._benefit_refresh()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_paid(self):
        if self.filtered('payslip_id') or self._locked_payslip_inputs():
            raise UserError(self.env._('This benefit line was already paid on a payslip and cannot be deleted. Archive it instead.'))


class HrPayrollBenefitAssign(models.TransientModel):
    _name = 'hr.payroll.benefit.assign'
    _description = 'Assign Employees to a Benefit'
    _check_company_auto = True

    benefit_id = fields.Many2one('hr.payroll.benefit', required=True)
    company_id = fields.Many2one(related='benefit_id.company_id')
    employee_ids = fields.Many2many('hr.employee', string='Employees', required=True, check_company=True)

    def action_assign(self):
        self.ensure_one()
        benefit = self.benefit_id
        existing = benefit.line_ids.employee_id
        self.env['hr.payroll.benefit.line'].create([{
            'benefit_id': benefit.id,
            'employee_id': employee.id,
            'company_amount': benefit.company_amount,
            'employee_amount': benefit.employee_amount,
        } for employee in self.employee_ids - existing])
        return {'type': 'ir.actions.act_window_close'}


class HrPayrollBenefitPayrun(models.TransientModel):
    _name = 'hr.payroll.benefit.payrun'
    _description = 'Generate a Separate Benefits Pay Run'

    name = fields.Char(required=True, default=lambda self: self.env._('Benefits'))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    date_start = fields.Date(string='From', required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_end = fields.Date(string='To', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) + relativedelta(months=1, days=-1))

    def action_generate(self):
        self.ensure_one()
        structure = self.env.ref('geo_payroll.structure_geo_benefits')
        lines = self.env['hr.payroll.benefit.line'].search([
            ('company_id', '=', self.company_id.id),
            ('benefit_id.active', '=', True),
            ('benefit_id.pay_mode', '=', 'separate'),
        ]).filtered(
            lambda line: line._in_period(self.date_start, self.date_end) and (
                (line.benefit_id.advance and not line.payslip_id
                 and line.currency_id.compare_amounts(line._advance_total(), 0.0) > 0)
                or (not line.benefit_id.advance
                    and line.currency_id.compare_amounts(line.company_amount, 0.0) > 0)))
        version_by_employee = {}
        for employee in lines.employee_id:
            if employee.company_id != self.company_id:
                continue
            version = employee._get_version(self.date_start) or employee._get_version(self.date_end)
            if (version and version.contract_date_start
                    and version.contract_date_start <= self.date_end
                    and (not version.contract_date_end
                         or version.contract_date_end >= self.date_start)):
                version_by_employee[employee] = version
        if not version_by_employee:
            raise UserError(self.env._('No separate-payment benefits found for this period.'))
        env = self.with_company(self.company_id).env
        run = env['hr.payslip.run'].create({
            'name': self.name,
            'structure_id': structure.id,
            'company_id': self.company_id.id,
            'date_start': self.date_start,
            'date_end': self.date_end,
        })
        slips = env['hr.payslip'].with_context(tracking_disable=True).create([{
            'name': self.env._('Benefits Payslip'),
            'employee_id': employee.id,
            'version_id': version.id,
            'company_id': self.company_id.id,
            'date_from': self.date_start,
            'date_to': self.date_end,
            'struct_id': structure.id,
            'payslip_run_id': run.id,
        } for employee, version in version_by_employee.items()])
        slips.compute_sheet()
        empty = run.slip_ids.filtered(lambda slip: not slip.input_line_ids.filtered('benefit_line_id'))
        if empty:
            empty.unlink()
        if not run.slip_ids:
            raise UserError(self.env._('No separate-payment benefits found for this period.'))
        action = self.env['ir.actions.act_window']._for_xml_id('hr_payroll.action_view_hr_payslip_month_form')
        action['domain'] = [('payslip_run_id', '=', run.id)]
        action['context'] = {'default_payslip_run_id': run.id}
        return action
