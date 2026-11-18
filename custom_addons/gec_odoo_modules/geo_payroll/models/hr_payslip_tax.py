from odoo import models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _gec_exemption_persons(self):
        """Employee records of the same persons in every company: one yearly allowance per person."""
        # sudo: the personal number is HR-private and records may sit in other companies
        employees = self.employee_id.sudo()
        numbers = [number for number in set(employees.mapped('identification_id')) if number]
        if not numbers:
            return employees
        return employees | employees.with_context(active_test=False).search([('identification_id', 'in', numbers)])

    def _gec_advance_payout(self):
        return sum(self.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE_PAY').mapped('amount'))

    def _gec_exemption_remaining(self):
        """Yearly art. 82 allowance left before this slip, or None without a category.
        Earlier payslips of the year, in any company, consume it first with their income after the employee pension;
        a refunded origin is reversed by its refund, so its validated correction counts in its place."""
        self.ensure_one()
        if not self.employee_id or not self.date_from:
            return None
        # Looked up on the whole person, so one company's record cannot leave the person taxed in full elsewhere.
        person = self._gec_exemption_persons()
        exemptions = self.env['hr.payroll.tax.exemption'].sudo().search([('employee_ids', 'in', person.ids)])
        if not exemptions:
            return None
        limit = max(exemptions.mapped('yearly_limit'))
        root = self._benefit_root_origin()
        family_ids = (self | root | root.related_payslip_ids).ids
        prior_slips = self.env['hr.payslip'].sudo().search([
            ('id', 'not in', family_ids),
            ('employee_id', 'in', person.ids),
            ('state', '!=', 'cancel'),
            ('credit_note', '=', False),
            ('is_refunded', '=', False),
            ('date_from', '>=', self.date_from.replace(month=1, day=1)),
            '|',
            ('date_from', '<', self.date_from),
            '&',
            ('date_from', '=', self.date_from),
            ('state', 'in', ('validated', 'paid')),
        ])
        lines = prior_slips.line_ids
        consumed = sum(lines.filtered(lambda line: line.code in ('GROSS', 'PENSION_EE')).mapped('total'))
        consumed -= sum(lines.filtered(lambda line: line.code == 'ADV_PEE_PRE').mapped('total'))
        consumed += prior_slips._gec_advance_payout()
        return max(0.0, self.company_id.currency_id.round(limit - consumed))

    def gec_advance_taxable_gross(self, gross):
        """While allowance is left, the monthly PIT line taxes the excess and nothing is prepaid."""
        self.ensure_one()
        remaining = self._gec_exemption_remaining()
        if remaining is not None and remaining > 0:
            return 0.0
        return gross

    def gec_pit_taxable_gross(self, gross, pension=0.0, advance_pension=0.0):
        """Income-tax base: the employee pension comes off first, in full, then the art. 82 allowance left (accountant,
        2026-11-11). While allowance is left, an advance pay-out joins the base with its pension."""
        self.ensure_one()
        remaining = self._gec_exemption_remaining()
        if not remaining:
            return gross - pension
        own_advance = self._gec_advance_payout()
        return max(0.0, gross + own_advance - pension - advance_pension - remaining)

    def gec_pit_explanation(self, gross, taxable, pension, tax, advance_pension=0.0):
        """Tooltip of the Income Tax line: how the base was reached after the employee pension, and the rate."""
        self.ensure_one()
        money = self._gec_money
        remaining = self._gec_exemption_remaining()
        own_advance = self._gec_advance_payout()
        if remaining and own_advance:
            text = self.env._("Taxable income = gross %(gross)s + advance pay-out %(advance)s - employee pension %(pension)s"
                " - tax exemption left %(remaining)s = %(taxable)s.", gross=money(gross), advance=money(own_advance),
                pension=money(pension + advance_pension), remaining=money(remaining), taxable=money(taxable))
        elif remaining:
            text = self.env._("Taxable income = gross %(gross)s - employee pension %(pension)s - tax exemption left %(remaining)s = %(taxable)s.",
                gross=money(gross), pension=money(pension), remaining=money(remaining), taxable=money(taxable))
        elif remaining is None and pension:
            text = self.env._("Taxable income = gross %(gross)s - employee pension %(pension)s = %(taxable)s.",
                gross=money(gross), pension=money(pension), taxable=money(taxable))
        elif remaining is None:
            text = self.env._("Taxable income = gross %(gross)s.", gross=money(gross))
        elif pension:
            text = self.env._("Taxable income = gross %(gross)s - employee pension %(pension)s = %(taxable)s"
                " (the yearly tax exemption is used up).", gross=money(gross), pension=money(pension), taxable=money(taxable))
        else:
            text = self.env._("Taxable income = gross %(gross)s (the yearly tax exemption is used up).", gross=money(gross))
        tax_text = self.env._("Income tax = %(rate)s × %(base)s = %(tax)s.", rate="%g%%" % self._rule_parameter('gec_ge_pit_rate'),
            base=money(taxable), tax=money(tax))
        return {'explanation': f"{text} {tax_text}"}

    def gec_net_explanation(self, gross, deductions, advance, net):
        """Tooltip of the Net line: gross, deductions and any advance paid out; deductions come in positive."""
        self.ensure_one()
        money = self._gec_money
        if advance:
            text = self.env._("Net = gross %(gross)s - deductions %(deductions)s + advance pay-out %(advance)s = %(net)s.", gross=money(gross),
                deductions=money(deductions), advance=money(advance), net=money(net))
        else:
            text = self.env._("Net = gross %(gross)s - deductions %(deductions)s = %(net)s.",
                              gross=money(gross), deductions=money(deductions), net=money(net))
        return {'explanation': text}

    def _gec_check_current_exemption_tax(self):
        """Manually edited lines are replayed, so an edit alone never looks like a changed allowance."""
        self.ensure_one()
        if self.credit_note or self.origin_payslip_id or self.state != 'draft':
            return
        pit_rules = self.struct_id.rule_ids.filtered(
            lambda rule: rule.code == 'PIT'
            and 'gec_pit_taxable_gross' in (rule.amount_python_compute or ''))
        if not pit_rules or self._gec_exemption_remaining() is None:
            return
        edits = {line.code: {
            'name': line.name,
            'amount': line.amount,
            'quantity': line.quantity,
            'rate': line.rate,
            'manually_modified': True,
        } for line in self.line_ids if line.manually_modified}
        expected = sum(vals['total'] for vals in self.with_context(force_payslip_line_overrides=edits)._get_payslip_lines() if vals['code'] == 'PIT')
        actual = sum(self.line_ids.filtered(lambda line: line.code == 'PIT').mapped('total'))
        if self.company_id.currency_id.compare_amounts(expected, actual) != 0:
            raise UserError(self.env._("The income tax exemption used by %(slip)s has changed: compute this payslip again and check it before "
                "validating (with a separate overtime payslip, validate one first, then compute the other again).", slip=self.display_name))
