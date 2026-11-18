from collections import defaultdict

from odoo import _, Command, models
from odoo.exceptions import UserError
from odoo.tools import format_date

from .account_batch_payment import GEC_PAYROLL_BATCH_WRITE_TOKEN
from odoo.addons.gec_bank.models.account_payment_method_line import bic_prefix

GEC_PAYROLL_BATCH_RESERVED_VALS = frozenset({'journal_id', 'batch_type', 'date', 'payment_ids', 'gec_payroll_is_batch', 'gec_payroll_kind',
    'gec_payroll_channel_id', 'payslip_run_id', 'gec_payroll_manual_ack'})


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_gec_pay_salaries(self):
        """Open the pay wizard for the selected validated payslips that still have an open salary or authority leg."""
        # sudo: payroll users may lack access to journal items.
        payable = self.filtered(lambda slip: slip.state == 'validated' and slip.sudo()._gec_payroll_has_open_legs())
        if not payable:
            raise UserError(_("These payslips have nothing left to pay: %s", ', '.join(self.mapped('display_name'))))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pay Salaries"),
            'res_model': 'hr.payroll.pay.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'gec_payroll_payslip_ids': payable.ids},
        }

    def _gec_payroll_valid_account_types(self, kind):
        """Account types the payment register accepts for this kind of leg.
        Salary runs carry the payroll context, which widens the set; authority runs do not."""
        payment = self.env['account.payment']
        if kind == 'salary':
            payment = payment.with_context(hr_payroll_payment_register=True)
        return payment._get_valid_payment_account_types()

    def _gec_payroll_net_account(self):
        self.ensure_one()
        rule = self.struct_id.rule_ids.filtered(lambda r: r.code == 'NET')[:1]
        return rule.with_company(self.company_id).account_credit

    def _gec_payroll_open_credit_lines(self):
        """Every open credit line of these payslips, including partner-less lines."""
        lines = self.env['account.move.line']
        for slip in self:
            lines |= slip.move_id.line_ids.filtered(lambda line: line.balance < 0 and not line.reconciled)
        return lines

    def _gec_payroll_net_lines(self):
        """Open lines on each payslip's NET account, valid or not.
        Matched by account first, so a missing employee contact cannot turn a salary into an authority payment."""
        lines = self.env['account.move.line']
        for slip in self:
            net_account = slip._gec_payroll_net_account()
            if net_account:
                lines |= slip._gec_payroll_open_credit_lines().filtered(lambda line: line.account_id == net_account)
        return lines

    def _gec_payroll_employee_lines(self):
        """The employee's own net lines: NET account and employee partner.
        Both are needed: the partner alone is not a net marker, the account alone catches other bookings."""
        valid = self._gec_payroll_valid_account_types('salary')
        lines = self.env['account.move.line']
        for slip in self:
            contact = slip.employee_id.work_contact_id
            if not contact:
                continue
            lines |= slip._gec_payroll_net_lines().filtered(
                lambda line: line.partner_id == contact
                and line.account_id.reconcile
                and line.account_id.account_type in valid)
        return lines

    def _gec_payroll_authority_lines(self):
        """Partnered legs owed to somebody other than the employee (pension, funds)."""
        valid = self._gec_payroll_valid_account_types('authority')
        lines = self.env['account.move.line']
        for slip in self:
            contact = slip.employee_id.work_contact_id
            candidates = slip._gec_payroll_open_credit_lines() - slip._gec_payroll_net_lines()
            lines |= candidates.filtered(
                lambda line: line.partner_id
                and line.partner_id != contact
                and line.account_id.reconcile
                and line.account_id.account_type in valid)
        return lines

    def _gec_payroll_unroutable_lines(self):
        """Partnered legs no payment can carry: wrong account type, or not reconcilable."""
        return (self._gec_payroll_open_credit_lines() - self._gec_payroll_employee_lines() - self._gec_payroll_authority_lines())

    def _gec_payroll_blocked_accounts(self):
        """Liability accounts left open on the payslips that no payment here settles.
        Credits on expense accounts are owed to nobody and are not listed."""
        return self._gec_payroll_unroutable_lines().account_id.filtered(lambda account: account.internal_group == 'liability')

    def _gec_payroll_is_settled(self):
        self.ensure_one()
        return not self._gec_payroll_net_lines()

    def _gec_payroll_salary_due(self):
        """The employee leg exists only on a positive net whose NET credit is still open."""
        self.ensure_one()
        return self.net_wage > 0 and not self._gec_payroll_is_settled()

    def _gec_payroll_has_open_legs(self):
        """Salary leg only on a positive net; authority legs are owed whatever the net."""
        self.ensure_one()
        return self._gec_payroll_salary_due() or bool(self._gec_payroll_authority_lines())

    def _gec_payroll_check_payable(self):
        """Every reason this run cannot go out, raised once."""
        errors = []
        no_partner = _("no partner")
        batched = self.company_id.filtered('batch_payroll_move_lines')
        if batched:
            errors.append(_("Shared payroll journal entries are enabled for %s, so the salary lines carry no employee. Disable Batch Payroll Move "
                "Lines, or pay from the accounting side.", ', '.join(batched.mapped('display_name'))))

        positive = self.filtered(lambda slip: slip._gec_payroll_salary_due())
        no_contact = positive.filtered(lambda slip: not slip.employee_id.work_contact_id)
        if no_contact:
            errors.append(_("These employees have no work contact, so no payment can be addressed to them: %s",
                ', '.join(no_contact.employee_id.mapped('name'))))

        sub_contact = positive.filtered(lambda slip:
            slip.employee_id.work_contact_id
            and slip.employee_id.work_contact_id.commercial_partner_id
            != slip.employee_id.work_contact_id
            and any(not line.employee_bank_account_id for line in slip._gec_payroll_net_lines()))
        if sub_contact:
            errors.append(_("The work contact of these employees is a child of another contact, so the salary would be paid to the parent company's "
                "bank account: %s", ', '.join(sub_contact.employee_id.mapped('name'))))

        no_net = self.filtered(lambda slip: not slip._gec_payroll_net_account())
        if no_net:
            errors.append(_("The NET salary rule has no credit account on the structure of: %s", ', '.join(no_net.mapped('display_name'))))

        invalid_net = self.env['account.move.line']
        for slip in positive:
            invalid_net |= slip._gec_payroll_net_lines() - slip._gec_payroll_employee_lines()
        if invalid_net:
            errors.append(_("These NET salary lines do not match the employee's current "
                "work contact or are not on a reconcilable payment account: %s",
                ', '.join(sorted(set("%s / %s" % (line.move_id.display_name, line.partner_id.display_name or no_partner) for line in invalid_net)))))

        strays = (self._gec_payroll_unroutable_lines() - self._gec_payroll_net_lines()).filtered(lambda line: line.account_id.reconcile)
        if strays:
            errors.append(_("These open amounts are owed to somebody but cannot be routed by this flow, and paying without them would leave the "
                "payslip half settled: %s",
                ', '.join(sorted(set("%s / %s" % (line.account_id.display_name, line.partner_id.display_name or no_partner) for line in strays)))))

        if errors:
            raise UserError('\n\n'.join(errors))

    def _gec_payroll_check_channels(self, groups):
        """Channel configuration and bank-specific pre-flight, raised once."""
        errors = []
        company = self.company_id
        by_channel = defaultdict(lambda: self.env['account.move.line'])
        for (channel, kind, _account_type, _currency), lines in groups.items():
            if not channel:
                errors.append(_("Every employee and authority needs a bank."))
                continue
            by_channel[(channel, kind)] |= lines
        for channel in {key[0] for key in by_channel}:
            errors.extend(channel._gec_bank_config_errors())
            if channel.company_id != company:
                errors.append(_("%(channel)s belongs to another company than the payslips.", channel=channel.display_name))
        for (channel, kind), lines in by_channel.items():
            company_currency = company.currency_id
            journal_currency = channel.journal_id.currency_id or channel.company_id.currency_id
            foreign = lines.filtered(lambda line: (line.currency_id or line.company_currency_id) != company_currency)
            if journal_currency != company_currency or foreign:
                errors.append(_("%(channel)s must pay payroll in the company's currency %(company)s; the journal uses %(journal)s and the selected "
                    "lines use %(lines)s.", channel=channel.display_name, company=company_currency.name, journal=journal_currency.name,
                    lines=', '.join(sorted(set((line.currency_id or line.company_currency_id).name for line in lines)))))
            errors.extend(self._gec_payroll_check_recipients(channel, lines))
            errors.extend(channel._gec_bank_check(kind, lines))
        if errors:
            raise UserError('\n\n'.join(dict.fromkeys(errors)))

    def _gec_payroll_check_recipients(self, channel, lines):
        """Validate the bank each line will be paid into, for this channel.
        A recipient with a Treasury Code is paid by that code and needs no bank account."""
        errors = []
        journal_bic = bic_prefix(channel.journal_id.bank_bic)
        missing = self.env['res.partner']
        untrusted = self.env['res.partner.bank']
        for line in lines.filtered(lambda line: not line.partner_id.commercial_partner_id.gec_treasury_code):
            bank = line._gec_bank_recipient_account(journal_bic)
            if not bank:
                missing |= line.partner_id
            elif not bank.allow_out_payment:
                untrusted |= bank
        if missing:
            errors.append(_("These recipients have no bank account (a budget recipient such as the State Treasury needs a Treasury Code on its "
                "contact instead): %s", ', '.join(sorted(missing.mapped('display_name')))))
        if untrusted:
            errors.append(_("These bank accounts are not trusted for outgoing payments; open the bank account and allow outgoing payments first: %s",
                ', '.join(sorted(untrusted.mapped('display_name')))))
        return errors

    def _gec_payroll_register_context(self, channel, kind, lines):
        """Context for one payment-register run.
        ``hr_payroll_payment_register`` is set for salary only: ``hr_payroll_account`` then
        calls ``ensure_one()`` on each payment's payslip, which an aggregated authority payment breaks."""
        context = {
            'active_model': 'account.move.line',
            'active_ids': lines.ids,
            'payment_consider_partner': True,
            'gec_payroll_run': True,
            'gec_bank_journal_bic': bic_prefix(channel.journal_id.bank_bic),
            'gec_payroll_residual_snapshot': {line.id: line.amount_residual for line in lines},
        }
        if kind == 'salary':
            context['hr_payroll_payment_register'] = True
        return context

    def _gec_payroll_pay(self, routing, authority_routing, payment_date, manual_ack=False):
        """Create the payments and one batch per channel, purpose and currency; return the batches action.
        routing: {payslip id: method line}; authority_routing: {(partner id, account id): method line}."""
        invalid = self.filtered(lambda slip: slip.state != 'validated')
        if invalid:
            raise UserError(_("Only confirmed payslips can be paid: %s", ', '.join(invalid.mapped('display_name'))))
        invalid_moves = self.filtered(lambda slip: not slip.move_id or slip.move_id.state not in ('draft', 'posted'))
        if invalid_moves:
            raise UserError(_("Every selected payslip must have a draft or posted journal entry: %s",
                ', '.join(invalid_moves.mapped('display_name'))))
        draft_moves = self.move_id.filtered(lambda move: move.state == 'draft')
        for move in draft_moves:
            locks = move._get_violated_lock_dates(move.date, move._affect_tax_report())
            if locks:
                slip = self.filtered(lambda slip: slip.move_id == move)[:1]
                raise UserError(_("The journal entry of payslip %(slip)s is dated %(date)s, in a period locked by %(locks)s: set the entry's date "
                    "to an open day or ask for a lock exception, then pay again.", slip=slip.display_name, date=format_date(self.env, move.date),
                    locks=self.env['res.company']._format_lock_dates(locks)))
        draft_moves.action_post()
        if len(self.company_id) != 1:
            raise UserError(_("Select payslips from a single company."))

        self._gec_payroll_check_payable()
        authority_lines = self._gec_payroll_authority_lines()
        salary_slips = self.filtered(lambda slip: slip._gec_payroll_salary_due())

        groups = defaultdict(lambda: self.env['account.move.line'])
        # Authority first: core's register links every source move of an aggregated payment,
        # so salary links made earlier would spread across the authority group.
        for line in authority_lines:
            channel = authority_routing.get((line.partner_id.id, line.account_id.id))
            groups[(channel, 'authority', line.account_id.account_type, line.currency_id)] |= line
        for slip in salary_slips:
            channel = routing.get(slip.id)
            for line in slip._gec_payroll_employee_lines():
                groups[(channel, 'salary', line.account_id.account_type, line.currency_id)] |= line
        self._gec_payroll_check_channels(groups)

        payments_by_batch = defaultdict(lambda: self.env['account.payment'])
        for (channel, kind, _account_type, currency), lines in groups.items():
            payments = self.env['account.payment.register'].with_context(
                **self._gec_payroll_register_context(channel, kind, lines)
            ).create({
                'journal_id': channel.journal_id.id,
                'payment_method_line_id': channel.id,
                'payment_date': payment_date,
                # Authority liabilities are consolidated; salaries stay one payment per payslip move.
                'group_payment': kind == 'authority',
            })._create_payments()
            self._gec_payroll_apply_channel_vals(channel, kind, payments)
            payments_by_batch[(channel, kind, currency)] |= payments

        self._gec_payroll_assert_settled(authority_lines, payment_date, salary_slips)
        batches = self._gec_payroll_create_batches(payments_by_batch, manual_ack)
        return self._gec_payroll_handoff(batches)

    def _gec_payroll_check_payment_account(self, payment):
        """Refuse a created payment whose receiver account is missing or not trusted.
        Checks the account Odoo really chose; a Treasury Code recipient needs none."""
        if payment.partner_id.commercial_partner_id.gec_treasury_code:
            return
        bank = payment.partner_bank_id
        if not bank or not (bank.account_number or '').strip():
            raise UserError(_("%s has no receiver bank account.", payment.display_name))
        if not bank.allow_out_payment:
            raise UserError(_("%s uses a receiver account that is not trusted for outgoing payments.", payment.display_name))

    def _gec_payroll_apply_channel_vals(self, channel, kind, payments):
        forbidden = self.env['account.payment']._gec_payroll_protected_fields()
        for payment in payments:
            self._gec_payroll_check_payment_account(payment)
            vals = channel._gec_bank_payment_vals(kind, payment)
            if not vals:
                continue
            clashing = forbidden & set(vals)
            if clashing:
                raise UserError(_("%(channel)s tried to set %(fields)s on an already posted payment. Those fields must be set before the payment is "
                    "created.", channel=channel.display_name, fields=', '.join(sorted(clashing))))
            payment.write(vals)

    def _gec_payroll_assert_settled(self, authority_lines, payment_date, salary_slips):
        """Nothing may be reported as paid unless its payable line really closed."""
        self.move_id.line_ids.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
        missed = salary_slips.filtered(lambda slip: not slip._gec_payroll_is_settled())
        if missed:
            raise UserError(_("The payment register did not settle these payslips, so nothing was created: %s",
                ', '.join(missed.mapped('display_name'))))
        open_authority = authority_lines.filtered(
            lambda line: not (line.currency_id or line.company_currency_id).is_zero(
                line.amount_residual_currency if line.currency_id else line.amount_residual))
        if open_authority:
            raise UserError(_("These authority amounts were not settled, so nothing was created: %s",
                ', '.join(sorted(set(open_authority.partner_id.mapped('display_name'))))))
        # With several legs, core's register can miss that the authority leg is reconciled;
        # once all liabilities are closed, use the native payslip transition.
        settled = self.filtered(lambda slip: slip.net_wage >= 0 and slip._gec_payroll_is_settled())
        not_paid = settled.filtered(lambda slip: slip.state != 'paid')
        if not_paid:
            not_paid.action_payslip_paid()
            not_paid.write({'paid_date': payment_date})
        not_paid = settled.filtered(lambda slip: slip.state != 'paid')
        if not_paid:
            raise UserError(_("The accounting lines were settled but these payslips were not marked paid, so nothing was created: %s",
                ', '.join(not_paid.mapped('display_name'))))

    def _gec_payroll_create_batches(self, payments_by_batch, manual_ack):
        Batch = self.env['account.batch.payment']
        batches = Batch.browse()
        run = self[:1].payslip_run_id
        if not run or any(slip.payslip_run_id != run for slip in self):
            run = self.env['hr.payslip.run']
        for (channel, kind, _currency), payments in payments_by_batch.items():
            if not payments:
                continue
            payment_dates = set(payments.mapped('date'))
            if len(payment_dates) != 1:
                raise UserError(_("A payroll batch cannot contain different payment dates."))
            vals = {
                'journal_id': channel.journal_id.id,
                'batch_type': 'outbound',
                'date': payment_dates.pop(),
                'payment_ids': [Command.set(payments.ids)],
                'gec_payroll_is_batch': True,
                'gec_payroll_kind': kind,
                'gec_payroll_channel_id': channel.id,
                'payslip_run_id': run.id if len(run) == 1 else False,
                'gec_payroll_manual_ack': (manual_ack and channel._gec_bank_channel_kind() == 'manual'),
            }
            extra = channel._gec_bank_batch_vals(kind)
            clashing = GEC_PAYROLL_BATCH_RESERVED_VALS & set(extra)
            if clashing:
                raise UserError(_("%(channel)s tried to overwrite %(fields)s on the payroll batch.", channel=channel.display_name,
                    fields=', '.join(sorted(clashing))))
            vals.update(extra)
            batch = Batch.with_context(gec_payroll_batch_write_token=GEC_PAYROLL_BATCH_WRITE_TOKEN).create(vals)
            if vals['gec_payroll_manual_ack']:
                batch.message_post(body=_("%(user)s recorded this payroll batch for manual transfer: %(amount)s %(currency)s.",
                    user=self.env.user.display_name, amount=sum(payments.mapped('amount')), currency=payments.currency_id.name))
            batches |= batch
        return batches

    def _gec_payroll_handoff(self, batches):
        """Open the new batches; each is approved and sent from its own form, not by this transaction."""
        return {
            'type': 'ir.actions.act_window',
            'name': _("Payroll Payment Batches"),
            'res_model': 'account.batch.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', batches.ids)],
        }
