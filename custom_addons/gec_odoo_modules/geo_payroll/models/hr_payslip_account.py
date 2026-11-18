from collections import defaultdict

from odoo import Command, models
from odoo.exceptions import UserError
from odoo.tools import format_date


# Payslip line code -> benefit input codes it is made of, for the vendor split.
BENEFIT_VENDOR_INPUT_CODES = {'BENEFIT_DED': 'BENEFIT_DED', 'BENEFIT_KIND_DED': 'BENEFIT_KIND'}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _prepare_slip_lines(self, date, line_ids, line_index=None):
        """No line to split (no account, or "Split on names" on) refuses the entry: the vendor would go unpaid."""
        new_lines = super()._prepare_slip_lines(date, line_ids, line_index)
        if self.company_id.batch_payroll_move_lines:
            return new_lines
        currency = self.company_id.currency_id
        for line_code, input_code in BENEFIT_VENDOR_INPUT_CODES.items():
            by_vendor = defaultdict(float)
            for line_input in self.input_line_ids.filtered(lambda inp: inp.code == input_code):
                vendor = line_input.benefit_line_id.benefit_id.partner_id
                if vendor:
                    by_vendor[vendor] += line_input.amount
            if not by_vendor:
                continue
            rule = self.line_ids.salary_rule_id.filtered(lambda r: r.code == line_code)[:1]
            account = rule.with_company(self.company_id).account_debit
            vals = next((
                line_vals for line_vals in new_lines
                if account and line_vals['name'] == rule.name and line_vals['account_id'] == account.id
            ), None)
            if not vals:
                raise UserError(self.env._("Payslip %(slip)s pays benefit vendors, but salary rule %(rule)s has no account or has 'Split on names' "
                    "ticked. Set its account and untick 'Split on names'.", slip=self.name, rule=rule.name or line_code))
            side = 'credit' if vals['credit'] else 'debit'
            sign = 1 if vals[side] > 0 else -1
            vendor_lines = []
            for vendor, vendor_amount in by_vendor.items():
                share = sign * abs(vendor_amount)
                payable = vendor.with_company(self.company_id).property_account_payable_id
                vendor_vals = dict(vals, account_id=payable.id, partner_id=vendor.id, name=f"{vals['name']} - {vendor.display_name}",
                    tax_ids=[Command.link(tax.id) for tax in payable.tax_ids])
                vendor_vals[side] = share
                vendor_lines.append(vendor_vals)
                vals[side] -= share
            position = next(index for index, line_vals in enumerate(new_lines) if line_vals is vals)
            if currency.is_zero(vals[side]):
                new_lines.pop(position)
            new_lines[position:position] = vendor_lines
        return new_lines

    def _gec_net_account(self):
        self.ensure_one()
        net_rule = self.struct_id.rule_ids.filtered(lambda r: r.code == 'NET')[:1]
        return net_rule.with_company(self.company_id).account_credit

    def _gec_net_payable_lines(self):
        lines = self.env['account.move.line']
        for slip in self:
            net_account = slip._gec_net_account()
            if net_account:
                lines |= slip.move_id.line_ids.filtered(lambda l: l.account_id == net_account and not l.reconciled)
        return lines

    def _gec_net_settled(self):
        """True when the NET account is set and none of its lines is open; withholding legs do not count."""
        self.ensure_one()
        return bool(self._gec_net_account()) and not self.sudo()._gec_net_payable_lines()

    def _gec_mark_settled_paid(self, paid_date=False, paid_slips=None):
        """A correction waits while another of the same origin has an open NET line."""
        for slip in self.filtered(lambda s: s.state == 'validated' and s.move_id and s._gec_net_settled()):
            if slip.is_correction_payslip and any(
                other != slip and other.is_correction_payslip and other.state == 'validated'
                and other.sudo()._gec_net_payable_lines()
                for other in slip.origin_payslip_id.related_payslip_ids
            ):
                continue
            if paid_slips is None or slip in paid_slips:
                date = paid_date or slip.paid_date
            else:
                date = slip.paid_date or paid_date
            slip.action_payslip_paid()
            if date and slip.paid_date != date:
                slip.paid_date = date

    def action_payslip_paid(self):
        """Core pays a correction's whole family; a member whose NET line is still open stays validated."""
        if 'gec_paid_cascade_skip_ids' in self.env.context:
            skipped = self.browse(self.env.context['gec_paid_cascade_skip_ids'])
        else:
            family = self.origin_payslip_id | self.origin_payslip_id.related_payslip_ids
            skipped = (family - self).filtered(lambda slip: slip.state == 'validated' and slip.sudo()._gec_net_payable_lines())
        slips = (self - skipped).with_context(gec_paid_cascade_skip_ids=skipped.ids)
        return super(HrPayslip, slips).action_payslip_paid()

    def action_payslip_unpaid(self):
        """Clear the Payment Date of slips whose NET payment was undone; a reopened NET line means unpaid."""
        res = super().action_payslip_unpaid()
        self.filtered(
            lambda slip: slip.paid_date and slip.move_id.sudo().matched_payment_ids
            and slip.sudo()._gec_net_payable_lines()
        ).write({'paid_date': False})
        return res

    def _gec_open_lines(self):
        return self.move_id.line_ids.filtered(lambda line: line.account_id.reconcile and not line.currency_id.is_zero(line.amount_residual_currency))

    def _gec_settle_correction_family(self):
        """Net an origin's entries with its refunds, then the refunds' remainder with its corrections."""
        def is_usable(slip):
            return slip.state in ('validated', 'paid') and slip.move_id and slip.move_id.sudo().state != 'cancel'

        def reconcile_by_key(lines, net_account_ids):
            groups = defaultdict(lambda: self.env['account.move.line'].sudo())
            for line in lines:
                if line.account_id.id in net_account_ids:
                    groups[line.account_id.id, None] |= line
                else:
                    groups[line.account_id.id, line.partner_id.id] |= line
            for group in groups.values():
                if any(line.balance > 0 for line in group) and any(line.balance < 0 for line in group):
                    group.reconcile()

        for origin in self.origin_payslip_id:
            if origin.company_id.batch_payroll_move_lines or not is_usable(origin):
                continue
            related = origin.related_payslip_ids.filtered(is_usable)
            refunds = related.filtered('is_refund_payslip')
            corrections = related.filtered('is_correction_payslip')
            family = origin | refunds | corrections
            drafts = family.move_id.sudo().filtered(lambda move: move.state == 'draft' and move.line_ids)
            for move in drafts:
                locks = move._get_violated_lock_dates(move.date, move._affect_tax_report())
                if locks:
                    slip = family.filtered(lambda slip: slip.move_id == move)[:1]
                    raise UserError(self.env._("The journal entry of payslip %(slip)s is dated %(date)s, in a period locked by %(locks)s: set the "
                        "entry's date to an open day or ask for a lock exception, then validate again.", slip=slip.display_name,
                        date=format_date(self.env, move.date), locks=self.env['res.company']._format_lock_dates(locks)))
            drafts.action_post()
            net_account_ids = {slip._gec_net_account().id for slip in family}
            if refunds:
                reconcile_by_key((origin | refunds).sudo()._gec_open_lines(), net_account_ids)
                if corrections:
                    reconcile_by_key((refunds | corrections).sudo()._gec_open_lines(), net_account_ids)
            owed = corrections.filtered(lambda slip: slip.has_negative_net_to_report and slip.sudo()._gec_net_payable_lines())
            owed.write({'has_negative_net_to_report': False, 'negative_net_to_report': 0.0})
            if origin.state == 'paid':
                family._gec_mark_settled_paid()

    def action_register_payment(self):
        """One payslip at a time: grouped authority payments over two entries crash core's hook."""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError(self.env._("You can only register payments for unpaid payslips."))
        if self.move_id and self.move_id.state != 'posted':
            raise UserError(self.env._("You can only register payments for posted journal entries."))
        if any(not bank.allow_out_payment for bank in self.employee_id.sudo().bank_account_ids):
            raise UserError(self.env._("A bank account of this employee is not trusted: open the bank account and allow outgoing payments first."))
        if not self._gec_net_payable_lines():
            if self.origin_payslip_id or self.related_payslip_ids:
                raise UserError(self.env._("These payslips were corrected or refunded and have nothing left to pay: %(names)s",
                    names=self.display_name))
            raise UserError(self.env._("Nothing is left to pay on %(names)s: check that the Net Salary rule has a Credit Account for this company.",
                names=self.display_name))
        if not self._gec_net_account().reconcile:
            raise UserError(self.env._("Tick Allow Reconciliation on the Credit Account of the Net Salary rule, then try again."))
        valid_types = self.env['account.payment'].with_context(hr_payroll_payment_register=True)._get_valid_payment_account_types()
        payable = self._gec_open_lines().filtered(lambda line: line.account_id.account_type in valid_types)
        orphans = payable.filtered(lambda l: not l.partner_id)
        if orphans:
            raise UserError(self.env._("These payable salary lines have no partner, so no payment can be addressed for them. Set the third-party "
                "partner on their salary rule: %(details)s",
                details=', '.join(sorted(set("%s (%s)" % (line.account_id.display_name, line.name) for line in orphans)))))
        action = payable.action_register_payment(ctx={
            'default_partner_id': self.employee_id.work_contact_id.id,
            'default_partner_bank_id': self.employee_id.primary_bank_account_id.id,
            'default_company_id': self.company_id.id,
            'default_group_payment': True,
            'payment_consider_partner': True,
            'dont_redirect_to_payments': True,
            'hr_payroll_payment_register': True,
            'gec_payslip_register_payment': True,
        })
        return action

    def _gec_check_one_entry_per_payslip(self):
        """Refuse batch journal entries: validation runs in groups and the vendor split needs one entry per slip."""
        if self.filtered(lambda slip: slip.company_id.batch_payroll_move_lines and slip.company_id.country_code == 'GE'):
            raise UserError(self.env._("Georgian payroll posts one journal entry per payslip. Turn off 'Batch Payroll Move Lines' in the Payroll "
                "settings."))

    def _gec_release_journal_entries(self):
        """Like core's Cancel, but refuses posted entries a user cannot release, corrected slips and matched entries."""
        slips = self.filtered('move_id')
        to_release = slips.move_id.sudo().filtered(lambda move: move.state != 'cancel' and not move.reversal_move_ids)
        posted = to_release.filtered('posted_before')
        if posted and not self.env.su and not self.env.user.has_group('account.group_account_invoice'):
            raise UserError(self.env._("These payslips are linked to a posted journal entry, only a user with accounting rights can release it: "
                "%(names)s", names=', '.join(slips.filtered(lambda slip: slip.move_id in posted).mapped('name'))))
        corrected = slips.filtered(lambda slip: any(rel.state in ('validated', 'paid') for rel in slip.related_payslip_ids - slips))
        if corrected:
            raise UserError(self.env._("These payslips have a validated refund or correction: %(names)s. Cancel the correction and its refund "
                "first.", names=', '.join(corrected.mapped('name'))))
        matched = self.env['hr.payslip']
        family_partials = self.env['account.partial.reconcile'].sudo()
        for slip in slips.filtered(lambda slip: slip.move_id.sudo() in to_release):
            origin = slip.origin_payslip_id
            family = slip | origin | origin.related_payslip_ids | slip.related_payslip_ids
            lines = slip.move_id.sudo().line_ids
            for partial in lines.matched_debit_ids | lines.matched_credit_ids:
                if (partial.debit_move_id.move_id | partial.credit_move_id.move_id) - family.move_id.sudo():
                    matched |= slip
                else:
                    family_partials |= partial
        if matched:
            raise UserError(self.env._("The journal entry of these payslips is matched with a payment or a bank statement line: %(names)s. "
                "Cancel or unreconcile that payment first, then try again.", names=', '.join(matched.mapped('name'))))
        family_partials.unlink()
        to_release._unlink_or_reverse()
        slips.write({'move_id': False})
