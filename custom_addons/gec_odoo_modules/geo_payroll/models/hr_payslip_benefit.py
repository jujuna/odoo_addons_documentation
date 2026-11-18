from collections import Counter

from odoo import Command, api, models
from odoo.exceptions import UserError


# Repayment line code -> pay-out line code of the prepaid amount it closes.
ADVANCE_PREPAID_CODES = {'REPAY_PEE': 'ADV_PEE_PRE', 'REPAY_PIT': 'ADV_PIT_PRE', 'REPAY_PER': 'ADV_PER_PRE'}
# Input code -> sign of its amount in the line total of the same code (ADVANCE_PAY is checked by existence: its line is net of tax).
BENEFIT_INPUT_LINE_SIGN = {'BONUS': 1, 'BENEFIT_KIND': 1, 'BENEFIT_DED': -1, 'ADVANCE': -1}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    @api.model
    def _gec_drop_copied_benefit_inputs(self, vals_list):
        """Drop benefit inputs copied without their benefit link; they are re-added with it, not paid twice."""
        for vals in vals_list:
            if not vals.get('origin_payslip_id') or not vals.get('input_line_ids'):
                continue
            origin = self.browse(vals['origin_payslip_id'])
            copies = Counter((line.salary_rule_id.id, line.name, line.amount) for line in origin.input_line_ids if line.benefit_line_id)
            if not copies:
                continue
            kept = []
            for command in vals['input_line_ids']:
                values = command[2] if command[0] == Command.CREATE else None
                key = values and (values.get('salary_rule_id'), values.get('name'), values.get('amount'))
                if key and not values.get('benefit_line_id') and copies[key]:
                    copies[key] -= 1
                    continue
                kept.append(command)
            vals['input_line_ids'] = kept

    def gec_advance_repay_share(self, advance_input, repay_code):
        """Part of the prepaid amount one repayment installment closes (REPAY_PEE, REPAY_PIT or REPAY_PER).
        Proportional to what the pay-out slip prepaid; the last installment closes the remainder;
        corrections of one chain count as one."""
        self.ensure_one()
        if len(advance_input) > 1:
            return round(sum(self.gec_advance_repay_share(line, repay_code) for line in advance_input), 2)
        benefit_line = advance_input.benefit_line_id
        payout = benefit_line.payslip_id
        if not payout:
            return 0.0
        payouts = payout.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE_PAY')
        total = sum(payouts.mapped('amount'))
        own = sum(payouts.filtered(lambda inp: inp.benefit_line_id == benefit_line).mapped('amount'))
        prepaid = sum(payout.line_ids.filtered(lambda line: line.code == ADVANCE_PREPAID_CODES[repay_code]).mapped('total'))
        if not total or not prepaid:
            return 0.0
        root = self._benefit_root_origin()
        others = [
            carrier for carrier in benefit_line._advance_carrier_inputs(exclude_payslip=self)
            if carrier.payslip_id._benefit_root_origin() != root]
        if max(benefit_line.benefit_id.payslip_count, 1) - len(others) > 1:
            return round(prepaid * advance_input.amount / total, 2)
        closed = 0.0
        for carrier in others:
            slip = carrier.payslip_id
            repay_lines = slip.line_ids.filtered(lambda line: line.code == repay_code)
            alone = slip.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE') == carrier
            closed += (sum(repay_lines.mapped('total')) if repay_lines and alone else round(prepaid * carrier.amount / total, 2))
        return round(prepaid * own / total - closed, 2)

    def _compute_input_line_ids(self):
        overtime = self.filtered(lambda slip: slip._gec_is_overtime())
        # Stock salary attachments fit every structure but must not consume anything on overtime.
        for slip in overtime:
            slip.input_line_ids = [Command.clear()]
        salary_slips = self - overtime
        super(HrPayslip, salary_slips)._compute_input_line_ids()
        for slip in salary_slips:
            commands = slip._benefit_input_commands()
            if commands:
                slip.update({'input_line_ids': commands})

    def _benefit_root_origin(self):
        self.ensure_one()
        root = self
        while root.origin_payslip_id:
            root = root.origin_payslip_id
        return root

    def _benefit_eligible_lines(self, pay_mode):
        """Benefit lines this slip should pay, minus those another live slip already carries."""
        self.ensure_one()
        domain = [('employee_id', '=', self.employee_id.id), ('company_id', '=', self.company_id.id), ('benefit_id.active', '=', True)]
        if pay_mode == 'separate':
            # Separate slips carry separate bonuses and advance pay-outs, never repayments.
            domain += [('benefit_id.pay_mode', '=', 'separate')]
        else:
            # Salary slips carry with-salary items and pay-outs, and all repayments.
            domain += ['|', ('benefit_id.pay_mode', '=', 'with_salary'), ('benefit_id.advance', '=', True)]
        eligible = self.env['hr.payroll.benefit.line'].sudo().search(domain).filtered(
            lambda line: line._in_period(self.date_from, self.date_to, payslip=self))
        if not eligible:
            return eligible
        others = self.env['hr.payslip.input'].sudo().search([
            ('benefit_line_id', 'in', eligible.ids),
            ('payslip_id', '!=', self.id),
            ('payslip_id.state', '!=', 'cancel'),
            ('payslip_id.credit_note', '=', False),
            ('payslip_id.origin_payslip_id', '=', False),
        ])
        blocked = set()
        for other in others:
            line = other.benefit_line_id
            if line.benefit_id.advance:
                # One live slip only may carry the pay-out of an unstamped line.
                if not line.payslip_id and other.code == 'ADVANCE_PAY':
                    blocked.add(line.id)
                continue
            if line.benefit_id.recurrence == 'once':
                blocked.add(line.id)
            # Monthly: block on overlap or same month, so split slips do not both pay.
            elif ((other.payslip_id.date_from <= self.date_to
                    and other.payslip_id.date_to >= self.date_from)
                    or (other.payslip_id.date_from.year, other.payslip_id.date_from.month)
                    == (self.date_from.year, self.date_from.month)):
                blocked.add(line.id)
        for line in eligible.filtered(lambda line: line.benefit_id.advance):
            payout_slip = line.payslip_id
            if not payout_slip or payout_slip == self:
                if (line.benefit_id.pay_mode == 'separate') != (pay_mode == 'separate'):
                    blocked.add(line.id)
            elif pay_mode == 'separate':
                # Repayments never ride a separate Benefits slip.
                blocked.add(line.id)
            elif ((self.date_from.year, self.date_from.month) <= (payout_slip.date_from.year, payout_slip.date_from.month)):
                # Repayments start the month after the pay-out slip's period.
                blocked.add(line.id)
        repaying = eligible.filtered(lambda line: line.benefit_id.advance and line.id not in blocked and line.payslip_id and line.payslip_id != self)
        if repaying:
            counts = {}
            for carrier in repaying._advance_carrier_inputs(exclude_payslip=self):
                counts[carrier.benefit_line_id.id] = counts.get(carrier.benefit_line_id.id, 0) + 1
            for line in repaying:
                if counts.get(line.id, 0) >= max(line.benefit_id.payslip_count, 1):
                    blocked.add(line.id)
        return eligible.filtered(lambda line: line.id not in blocked)

    def _benefit_mirror_root_inputs(self):
        """A correction copies the chain root's benefit inputs once, at creation, so a benefit is paid once and later edits stay."""
        self.ensure_one()
        rules = {rule.code: rule for rule in self.struct_id.rule_ids}
        return [Command.create({
            'salary_rule_id': rules.get(line.code, line.salary_rule_id).id,
            'name': line.name,
            'amount': line.amount,
            'benefit_line_id': line.benefit_line_id.id,
        }) for line in self._benefit_root_origin().input_line_ids.filtered('benefit_line_id')]

    def _benefit_input_commands(self):
        """Refunds and corrections get no fresh inputs here; a correction mirrors its root's once, at creation."""
        self.ensure_one()
        # Skip NewId records: the blocking search would strip the slip's own stored inputs.
        if not isinstance(self.id, int):
            return []
        if self.state != 'draft' or self.edited or self.credit_note or self.is_refund_payslip or self.origin_payslip_id:
            return []
        commands = [Command.unlink(line.id) for line in self.input_line_ids.filtered('benefit_line_id')]
        if not self.employee_id or not self.date_from or not self.date_to or not self.struct_id:
            return commands
        rules = {rule.code: rule for rule in self.struct_id.rule_ids}
        benefits_struct = self.env.ref('geo_payroll.structure_geo_benefits', raise_if_not_found=False)
        if benefits_struct and self.struct_id == benefits_struct:
            pay_mode = 'separate'
        elif self._gec_is_unedited_draft_base():
            pay_mode = 'with_salary'
        else:
            return commands
        currency = self.company_id.currency_id
        for line in self._benefit_eligible_lines(pay_mode):
            benefit = line.benefit_id
            if benefit.advance:
                if not line.payslip_id or line.payslip_id == self:
                    sides = [('ADVANCE_PAY', line._advance_total())]
                else:
                    sides = [('ADVANCE', line._advance_slip_amount(self))]
            elif pay_mode == 'separate':
                sides = [('BONUS', line.company_amount)]
            elif benefit.partner_id:
                sides = [('BENEFIT_KIND', line.company_amount), ('BENEFIT_DED', line.employee_amount)]
            else:
                sides = [('BONUS', line.company_amount), ('BENEFIT_DED', line.employee_amount)]
            for rule_code, amount in sides:
                if currency.compare_amounts(amount, 0.0) <= 0:
                    continue
                # Without a rule the benefit would be marked paid but pay nothing.
                if rule_code not in rules:
                    continue
                commands.append(Command.create({
                    'salary_rule_id': rules[rule_code].id,
                    'name': benefit.name,
                    'amount': amount,
                    'benefit_line_id': line.id,
                }))
        return commands

    def _benefit_record_consumption(self):
        for slip in self:
            if slip.credit_note or slip.origin_payslip_id:
                continue
            once_lines = slip.input_line_ids.benefit_line_id.sudo().filtered(
                lambda line: line.benefit_id.recurrence == 'once'
                and not line.benefit_id.advance and not line.payslip_id)
            payout_lines = slip.input_line_ids.filtered(
                lambda inp: inp.code == 'ADVANCE_PAY'
            ).benefit_line_id.sudo().filtered(lambda line: not line.payslip_id)
            (once_lines | payout_lines).write({'payslip_id': slip.id})

    def _benefit_release_consumption(self):
        lines = self.env['hr.payroll.benefit.line'].sudo().with_context(active_test=False).search([('payslip_id', 'in', self.ids)])
        for line in lines:
            domain = [
                ('benefit_line_id', '=', line.id),
                ('payslip_id', 'not in', self.ids),
                ('payslip_id.state', 'in', ('validated', 'paid')),
                ('payslip_id.credit_note', '=', False),
            ]
            if line.benefit_id.advance:
                domain.append(('salary_rule_id.code', '=', 'ADVANCE_PAY'))
            survivor = self.env['hr.payslip.input'].sudo().search(domain, limit=1, order='id desc')
            line.payslip_id = survivor.payslip_id

    def unlink(self):
        """Refresh the employee's other drafts after the delete, so a benefit blocked by a deleted draft becomes payable."""
        siblings = self.input_line_ids.benefit_line_id.sudo()._draft_slips() - self
        res = super().unlink()
        siblings._benefit_refresh()
        return res

    def _benefit_check_no_live_installments(self):
        payout_lines = self.env['hr.payroll.benefit.line'].sudo().search([('payslip_id', 'in', self.ids), ('benefit_id.advance', '=', True)])
        for line in payout_lines:
            carriers = self.env['hr.payslip.input'].sudo().search([
                ('benefit_line_id', '=', line.id),
                ('salary_rule_id.code', '=', 'ADVANCE'),
                ('payslip_id', 'not in', self.ids),
                ('payslip_id.state', 'in', ('validated', 'paid')),
                ('payslip_id.credit_note', '=', False),
            ])
            if carriers:
                raise UserError(self.env._("%(slip)s paid out an advance whose installments are already validated (%(names)s). "
                    "Correct it instead of cancelling.", slip=line.payslip_id.display_name,
                    names=', '.join(carriers.payslip_id.mapped('display_name'))))

    def _benefit_refresh(self):
        """Inputs rewritten by a compute never reach write(), so redo the lines core would redo on an input write."""
        if not self:
            return
        self.env.add_to_compute(self._fields['input_line_ids'], self)
        self.filtered('line_ids').compute_sheet()

    def _benefit_check_inputs_match_lines(self):
        """A stamp written at another slip's validation changes inputs without a compute; refuse until recomputed."""
        for slip in self.filtered(lambda slip: slip.state == 'draft' and not slip.edited and not slip.credit_note):
            currency = slip.company_id.currency_id
            inputs = slip.input_line_ids
            lines = slip.line_ids
            stale = ('ADVANCE_PAY' in inputs.mapped('code')) != ('ADVANCE_PAY' in lines.mapped('code'))
            for code, sign in BENEFIT_INPUT_LINE_SIGN.items():
                expected = sign * sum(inputs.filtered(lambda inp: inp.code == code).mapped('amount'))
                actual = sum(lines.filtered(lambda line: line.code == code).mapped('total'))
                stale = stale or currency.compare_amounts(expected, actual) != 0
            if stale:
                raise UserError(self.env._("The benefit inputs of %(slip)s changed after its last computation. "
                    "Compute the payslip again before validating.", slip=slip.display_name))
