import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .gec_bank_guard_mixin import GEC_BANK_WRITE_TOKEN

_logger = logging.getLogger(__name__)

# Core's key for undoing a statement match; account_online_payment lets it through.
GEC_BANK_BYPASS_KEY = 'bypass_batch_payment_online_status_protection'
# The transfer states every bank shares. A bank adds its own with selection_add and places
# them in _gec_bank_state_groups.
GEC_BANK_STATES = [
    ('pending', 'Pending'),
    ('awaiting_approval', 'Awaiting Approval'),
    ('approved', 'Approved'),
    ('sending', 'Sending'),
    ('sent', 'Sent'),
    ('confirmed', 'Confirmed'),
    ('failed', 'Failed'),
    ('unknown', 'Unknown'),
]
# Fields only the transfer flow writes (gec.bank.guard.mixin).
GEC_BANK_TRANSFER_FIELDS = frozenset({
    'gec_bank_state', 'gec_bank_reference', 'gec_bank_request_id', 'gec_bank_error',
    'gec_bank_approved_by', 'gec_bank_approved_date', 'gec_bank_confirmed_source', 'gec_bank_prepared_by',
})
# Transfers a status-poll cron reads per run: each is a bank call, and the run must end inside limit_time_real.
GEC_BANK_STATUS_POLL_LIMIT = 100


class AccountPayment(models.Model):
    """The transfer flow shared by the bank modules, like core's payment.transaction: one set of
    transfer fields and per-bank hooks keyed by ``gec_bank_code``. A bank opts in through
    account.payment.method.line._gec_bank_transfer_flow; Basis keeps its own flow."""

    _name = 'account.payment'
    _inherit = ['account.payment', 'gec.bank.guard.mixin']

    gec_bank_code = fields.Char(string='Bank Transfer Method', compute='_compute_gec_bank_code')
    gec_bank_state = fields.Selection(
        GEC_BANK_STATES, string='Bank State', compute='_compute_gec_bank_state', store=True,
        readonly=True, copy=False, tracking=True, index=True)
    gec_bank_reference = fields.Char(
        string='Bank Reference', readonly=True, copy=False, index='btree_not_null',
        help="The bank's own id for the transfer.")
    gec_bank_request_id = fields.Char(
        string='Bank Request ID', readonly=True, copy=False, index='btree_not_null',
        help="Our id for the transfer, sent with every attempt so the bank can refuse a second one.")
    gec_bank_error = fields.Char(string='Bank Error', readonly=True, copy=False)
    gec_bank_approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    gec_bank_approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    gec_bank_prepared_by = fields.Many2one(
        'res.users', string='Last Changed By', readonly=True, copy=False,
        help="Who last changed what the transfer is built from (amount, recipient, purpose); "
             "like the creator, this user cannot approve it.")
    gec_bank_confirmed_source = fields.Selection(
        [('statement', 'Bank Statement'), ('status', 'Status Check'), ('manual', 'Manual')],
        string='Confirmed By', readonly=True, copy=False)

    _gec_bank_reference_uniq = models.Constraint(
        'unique (company_id, payment_method_id, gec_bank_reference)',
        'This bank reference already exists for this company.',
    )
    _gec_bank_request_uniq = models.Constraint(
        'unique (company_id, payment_method_id, gec_bank_request_id)',
        'This bank request id already exists for this company.',
    )

    @api.depends('payment_type', 'payment_method_line_id')
    def _compute_gec_bank_code(self):
        """Method code of an outbound payment on a transfer-flow channel, else False.
        A bank that reads more fields in _gec_bank_transfer_flow adds them to the depends here."""
        for payment in self:
            line = payment.payment_method_line_id
            payment.gec_bank_code = (
                line.code if payment.payment_type == 'outbound' and line and line._gec_bank_transfer_flow()
                else False)

    @api.depends('gec_bank_code')
    def _compute_gec_bank_state(self):
        """A bank transfer starts Pending, other payments have no state; a state the flow set is kept."""
        for payment in self:
            if payment.gec_bank_code:
                payment.gec_bank_state = payment.gec_bank_state or 'pending'
            elif payment.gec_bank_state == 'pending':
                payment.gec_bank_state = False
            else:
                payment.gec_bank_state = payment.gec_bank_state

    @api.model
    def _gec_bank_state_groups(self):
        """Meaning of each transfer state; banks add their states to the groups they fit. at_bank: on its way
        or held, edits change nothing; held: Odoo's payment is sent; open: no final outcome, polled or
        matched; uncertain: bank may lack it; in_approval: unsent, edits reset it."""
        return {
            'at_bank': {'sending', 'sent', 'confirmed'},
            'held': {'sent', 'confirmed'},
            'open': {'sent', 'unknown'},
            'uncertain': {'sending', 'unknown'},
            'in_approval': {'awaiting_approval', 'approved'},
        }

    def _gec_bank_approval_kept_states(self):
        """States that keep an approval: approved and not sent, or at the bank. Any other state clears it."""
        groups = self._gec_bank_state_groups()
        return (groups['in_approval'] - {'awaiting_approval'}) | groups['at_bank']

    def _gec_bank_protected_fields(self):
        return super()._gec_bank_protected_fields() | GEC_BANK_TRANSFER_FIELDS

    @api.model
    def _gec_bank_label_for(self, code):
        """The name of the bank sending ``code`` transfers, for messages."""
        return _("Bank")

    def _gec_bank_label(self):
        return self._gec_bank_label_for(self[:1].gec_bank_code)

    def _gec_bank_connection_record(self):
        """The connection of this payment's bank (sudo), possibly empty; override per bank."""
        self.ensure_one()
        return self.env['gec.bank.connection.mixin']

    def _gec_bank_send_one(self):
        """Send this payment to its bank; return True or a notification (override per bank)."""
        raise UserError(_("This payment is not sent through a bank integration."))

    def _gec_bank_refresh_one(self):
        """Ask the bank for this transfer's status and record it (override per bank)."""
        return None

    def _gec_bank_new_request_vals(self):
        """Values a send claims with: the request id the bank deduplicates on (minted once, reused on retries)
        plus anything else to reserve; override per bank."""
        return {}

    def _gec_bank_payload_fields(self):
        """Fields the bank's instructions are built from; changing one voids the approval (override per bank)."""
        return frozenset()

    def _gec_bank_check_instructions(self):
        """Refuse what the bank rejects and a mis-set channel, before any claim or approval (override per bank)."""
        return None

    @api.model
    def _gec_bank_user_group_for(self, code):
        """xmlid of the group allowed to send, reset, recover, cancel or confirm ``code`` transfers;
        override per bank."""
        return None

    @api.model
    def _gec_bank_check_user(self, code):
        """Refuse a money action to a user outside the bank's User group; server side, as RPC reaches
        the methods directly."""
        group = self._gec_bank_user_group_for(code)
        if group and not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("Only %s users may send, reset, recover, cancel or confirm these transfers.",
                              self._gec_bank_label_for(code)))

    def _gec_bank_treasury_transfer(self):
        """True when the bank pays this transfer to a treasury code, not to the receiver account; override per bank."""
        self.ensure_one()
        return bool(self.partner_id.commercial_partner_id.gec_treasury_code)

    @api.model
    def _gec_bank_result_columns(self):
        """Columns a bank's answer may write; the durable UPDATE uses only these."""
        return {'gec_bank_state', 'gec_bank_reference', 'gec_bank_error', 'gec_bank_confirmed_source',
                'gec_bank_approved_by', 'gec_bank_approved_date', 'is_sent', 'state'}

    def _gec_bank_at_bank(self):
        """True when a bank holds or may hold this payment (on its way, at the bank, outcome unknown):
        its journal entry then cannot be undone. A bank with its own flow extends it."""
        self.ensure_one()
        return bool(self.gec_bank_code) and self.gec_bank_state in (
            self._gec_bank_state_groups()['at_bank'] | {'unknown'})

    def _gec_bank_check_not_at_bank(self):
        """Refuse to undo the journal entry of a payment a bank holds or may hold.
        Without the entry the bill reads unpaid and is paid again (as core's online payment)."""
        if self.env.context.get(GEC_BANK_BYPASS_KEY):
            return
        at_bank = self.filtered(lambda payment: payment._gec_bank_at_bank())
        if at_bank:
            raise UserError(_(
                "These payments are at the bank, or may be, so their journal entry cannot be "
                "reset, cancelled or deleted. Check them with the bank first (refresh, recover "
                "or resync): %s", ', '.join(at_bank.mapped('display_name'))))

    def _gec_bank_check_bank_kept(self):
        """Refuse a journal or bank account change that takes these held payments off their bank: their fences
        and status checks key on the bank, so the payment could be undone or paid again while the bank holds it."""
        lost = self.filtered(lambda payment: not payment._gec_bank_at_bank())
        if lost:
            raise UserError(_("These payments are at the bank, or may be, so their journal's bank cannot change: %s. "
                              "Settle them with the bank first.", ', '.join(lost.mapped('display_name'))))

    def _gec_bank_holds_unbooked(self):
        """True when the payment is at the bank and not yet matched with a statement line."""
        self.ensure_one()
        return self._gec_bank_at_bank() and not self.is_matched

    def _gec_bank_check_not_held(self):
        """Refuse to unmatch these payments or take them out of their batch while the bank holds
        the money unbooked. Statement unmatching passes with the same key as _gec_bank_check_not_at_bank."""
        if self.env.context.get(GEC_BANK_BYPASS_KEY):
            return
        held = self.filtered(lambda payment: payment._gec_bank_holds_unbooked())
        if held:
            raise UserError(_(
                "These payments are at the bank, or may be, so they cannot be unmatched from what "
                "they pay or taken out of their batch. Check them with the bank first (refresh, "
                "recover or resync): %s", ', '.join(held.mapped('display_name'))))

    def action_draft(self):
        self._gec_bank_check_not_at_bank()
        return super().action_draft()

    def action_cancel(self):
        self._gec_bank_check_not_at_bank()
        return super().action_cancel()

    def action_reject(self):
        self._gec_bank_check_not_at_bank()
        return super().action_reject()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_at_bank(self):
        self._gec_bank_check_not_at_bank()

    def _gec_bank_check_sendable(self):
        """Refuse what no bank may send: withholding at payment (the bank would pay the gross), a draft
        payment (no posted entry), or one no longer Paid (it would pay twice)."""
        withholding = self.filtered(
            lambda payment: payment.withholding_line_ids and payment.withhold != 'payment')
        if withholding:
            raise UserError(_(
                "These payments withhold tax at payment, so the bank would receive the gross "
                "amount: %s. Withholding is booked in the journal entry now: cancel the payment "
                "and pay the net from the entry.", ', '.join(withholding.mapped('display_name'))))
        draft = self.filtered(lambda payment: payment.state == 'draft')
        if draft:
            raise UserError(_(
                "Confirm these payments before sending them, so their journal entry exists "
                "before the money leaves the bank: %s", ', '.join(draft.mapped('display_name'))))
        done = self.filtered(lambda payment: payment.state != 'paid')
        if done:
            raise UserError(_(
                "These payments are already matched with the bank statement, rejected or "
                "cancelled, so they cannot be sent: %s", ', '.join(done.mapped('display_name'))))

    def _gec_bank_mirror_vals(self, outcome):
        """Core payment values for a bank's answer, as core's online payment maps a status: 'held' makes it
        sent; 'rejected' (no money moved) makes it Rejected and not sent. The statement reconciles an executed one."""
        self.ensure_one()
        vals = {}
        if outcome == 'held' and not self.is_sent:
            vals['is_sent'] = True
        elif outcome == 'rejected' and self.state == 'paid':
            vals['state'] = 'rejected'
            if self.is_sent:
                vals['is_sent'] = False
        return vals

    def _gec_bank_after_durable(self, vals):
        """Recompute the batch fields derived from ``is_sent`` and ``state`` after a durable write."""
        batch = self.batch_payment_id
        if batch and {'is_sent', 'state'} & set(vals):
            self.env.add_to_compute(batch._fields['state'], batch)
            self.env.add_to_compute(batch._fields['amount_residual'], batch)

    # Transfer flow: bank buttons call these with their own code, so a button only acts on its own bank's payments
    def _gec_bank_own(self, code):
        return self.filtered(lambda payment: payment.gec_bank_code == code)

    def _gec_bank_check_own(self, code):
        """Refuse one bank's action on a payment another bank, or none, sends."""
        if any(payment.gec_bank_code != code for payment in self):
            raise UserError(_("This payment is not an outbound %s transfer.",
                              self._gec_bank_label_for(code)))

    def _gec_bank_connection(self):
        """The usable connection of this payment's bank; missing or blocked raises."""
        self.ensure_one()
        connection = self._gec_bank_connection_record()
        errors = connection._gec_bank_unusable_errors(self.journal_id.company_id)
        if errors:
            raise UserError(errors[0])
        return connection

    def _gec_bank_processing_mode(self):
        connection = self._gec_bank_connection_record()
        return connection.processing_mode if connection else 'odoo_approve'

    def _gec_bank_submit_approval(self, code):
        """Submit pending transfers for approval in Odoo, checked as their send will be, and notify the approvers."""
        label = self._gec_bank_label_for(code)
        targets = self._gec_bank_own(code).filtered(lambda p: p.gec_bank_state == 'pending')
        if not targets:
            raise UserError(_("No pending %s transfer in this selection.", label))
        for payment in targets:
            connection = payment._gec_bank_connection()
            if connection.processing_mode != 'odoo_approve':
                raise UserError(_("The %s connection does not require approval in Odoo.", label))
            payment._gec_bank_check_sendable()
            payment._gec_bank_check_instructions()
            payment._gec_bank_internal_write({'gec_bank_state': 'awaiting_approval'})
            recipients = connection.approval_id.approver_user_ids().partner_id
            if recipients:
                payment.message_subscribe(partner_ids=recipients.ids)
                payment.message_post(body=_("Submitted for %s approval.", label), partner_ids=recipients.ids)
        return True

    def _gec_bank_approve(self, code):
        """Approve the selected transfers as an authorized approver who did not create them;
        refused without a usable connection, as the send is."""
        targets = self._gec_bank_own(code).filtered(lambda p: p.gec_bank_state == 'awaiting_approval')
        if not targets:
            raise UserError(_("No %s transfer awaiting approval in this selection.",
                              self._gec_bank_label_for(code)))
        for payment in targets:
            connection = payment._gec_bank_connection()
            connection.approval_id._gec_bank_check_approver(
                payment, connection.allow_self_approval, connection._gec_bank_label())
            payment._gec_bank_internal_write({'gec_bank_state': 'approved',
                                              'gec_bank_approved_by': self.env.user.id,
                                              'gec_bank_approved_date': fields.Datetime.now()})
        return True

    def _gec_bank_check_transfer(self, code):
        """Refuse, before any claim, what no bank may send: another bank's payment, an untrusted receiver account
        (treasury has none), a missing approval where Odoo approves, an unknown last outcome, a payment not Paid."""
        self.ensure_one()
        self.check_access('write')
        self._gec_bank_check_user(code)
        self._gec_bank_check_own(code)
        bank = self.partner_bank_id
        if bank and not bank.allow_out_payment and not self._gec_bank_treasury_transfer():
            raise UserError(_("%s: the receiver's bank account is not trusted yet; ask a user who may validate bank accounts "
                              "to switch on 'Trust bank account' on it, then send again.", self.display_name))
        if self.gec_bank_state == 'unknown':
            raise UserError(_("The outcome of the previous send is unknown. Recover it from the "
                              "bank first - resending could pay twice."))
        if self.gec_bank_state == 'failed':
            raise UserError(_("This transfer failed. Correct it, then use Reset to Pending before "
                              "sending it again."))
        if self.is_sent:
            raise UserError(_("This payment was already sent."))
        if self._gec_bank_processing_mode() == 'odoo_approve':
            self._gec_bank_check_approved()
        self._gec_bank_check_sendable()

    def _gec_bank_check_approved(self):
        """Where Odoo approves, require an approval by someone who may still approve; otherwise
        withdraw it durably so the transfer can be submitted again."""
        if not self.gec_bank_approved_by:
            raise UserError(_("This transfer must be approved in Odoo before sending."))
        approval = self._gec_bank_connection_record().approval_id
        if approval and approval.sudo().user_can_approve(self.gec_bank_approved_by):
            return
        approver = self.gec_bank_approved_by.display_name
        self._gec_bank_write_result({'gec_bank_state': 'pending'})
        raise UserError(_("%s approved this transfer but may no longer approve, so the approval was "
                          "withdrawn. Submit it for approval again.", approver))

    def _gec_bank_send_each(self, code):
        """Send each payment in its own savepoint so one failure does not roll back siblings.
        Returns the payments whose send ran, the refusals as 'payment: reason' lines, and the last notification."""
        done = self.browse()
        errors = []
        notice = None
        for payment in self:
            try:
                with self.env.cr.savepoint():
                    payment._gec_bank_check_own(code)
                    result = payment._gec_bank_send_one()
                done |= payment
                if isinstance(result, dict):
                    notice = result
            except UserError as exc:
                errors.append("%s: %s" % (payment.display_name, exc.args[0] if exc.args else exc))
        return done, errors, notice

    def _gec_bank_send_transfers(self, code):
        """Send the selected transfers and report outcomes from the resulting states, not from the call returning."""
        self._gec_bank_check_user(code)
        if len(self) == 1:
            self._gec_bank_check_own(code)
            return self._gec_bank_send_one()
        done, errors, notice = self._gec_bank_send_each(code)
        return self._gec_bank_report_sends(code, done, errors, notice)

    def _gec_bank_report_sends(self, code, done, errors, notice=None):
        """Notify the outcome of several sends: held, refused or in doubt, and each refusal with its reason."""
        counts = done._gec_bank_count_outcomes()
        label = self._gec_bank_label_for(code)
        if not errors and not counts['failed'] and not counts['uncertain']:
            return notice or self._gec_bank_notify(
                label, _("%(sent)s transfer(s) sent.", sent=counts['sent']), 'success')
        return self._gec_bank_notify(label, _(
            "%(sent)s sent, %(failed)s failed, %(uncertain)s uncertain.\n%(details)s",
            sent=counts['sent'], failed=counts['failed'] + len(errors),
            uncertain=counts['uncertain'], details='\n'.join(errors)), 'warning')

    def _gec_bank_count_outcomes(self):
        """Count the payments the bank holds, refused or left in doubt, from their states."""
        groups = self._gec_bank_state_groups()
        states = self.mapped('gec_bank_state')
        return {
            'sent': sum(state in groups['held'] for state in states),
            'failed': states.count('failed'),
            'uncertain': sum(state in groups['uncertain'] for state in states),
        }

    def _gec_bank_reserve_send(self):
        """Claim this payment for sending, durably, before any money moves; returns the claim values.
        gec.bank.service._reserve_send commits request id and 'sending' at once; unknown outcome is not claimable:
        only the bank's recovery may allow a resend."""
        self.ensure_one()
        vals = dict(self._gec_bank_new_request_vals(), gec_bank_state='sending')
        blocked = self._gec_bank_state_groups()['at_bank'] | {'unknown'}
        if not self.env['gec.bank.service']._reserve_send(self, vals, 'gec_bank_state', tuple(blocked)):
            raise UserError(_("This transfer is already being sent, was already sent, or its outcome "
                              "is unknown (recover it from the bank). Reload the payment to see its "
                              "current state."))
        return vals

    def _gec_bank_write_result(self, vals):
        """Record a bank's answer durably, never by ORM (an ORM write of the claimed row fails at commit and
        re-runs the request). State change posted here (no tracking); a state keeping no approval clears it."""
        self.ensure_one()
        unknown = set(vals) - self._gec_bank_result_columns()
        if unknown:
            raise ValueError("_gec_bank_write_result cannot write %s" % sorted(unknown))
        old_state = self.gec_bank_state
        new_state = vals.get('gec_bank_state')
        vals = dict(vals, **self._gec_bank_payment_state_vals(new_state))
        if new_state and new_state not in self._gec_bank_approval_kept_states() and self.gec_bank_approved_by:
            vals.update(gec_bank_approved_by=False, gec_bank_approved_date=False)
        # The status poll writes only over the state it read: a statement confirming the transfer meanwhile wins.
        expected = ({'gec_bank_state': old_state} if self.env.context.get('gec_bank_poll') else None)
        durable = self.env['gec.bank.service']._durable_write(self, vals, expected_state=expected)
        if durable is None:
            return
        self._gec_bank_after_durable(vals)
        if durable and new_state and new_state != old_state:
            labels = dict(self._fields['gec_bank_state']._description_selection(self.env))
            self.message_post(body=_("%(bank)s state: %(old)s → %(new)s",
                                     bank=self._gec_bank_label(),
                                     old=labels.get(old_state, old_state or '-'),
                                     new=labels.get(new_state, new_state)))
        if durable and vals.get('state') == 'rejected':
            self.message_post(body=_("%s rejected this transfer, so the payment is marked Rejected. To send it again: "
                                     "Reset to Draft, correct it, Confirm, then Reset to Pending and send it.",
                                     self._gec_bank_label()))

    def _gec_bank_release_claim(self, previous_state, error):
        """Give back a claim the bank refused before processing (401 after a failed login, 429 rate limit): no
        transfer exists, so the payment returns to its state before the send instead of Failed and Rejected."""
        self.ensure_one()
        self._gec_bank_write_result({'gec_bank_state': previous_state or 'pending', 'gec_bank_error': error[:255]})

    def _gec_bank_payment_state_vals(self, state):
        """Odoo's payment fields for a bank state: held -> sent, failed -> Rejected (_gec_bank_mirror_vals)."""
        if state in self._gec_bank_state_groups()['held']:
            return self._gec_bank_mirror_vals('held')
        if state == 'failed':
            return self._gec_bank_mirror_vals('rejected')
        return {}

    def _gec_bank_confirm_manual(self, code):
        """Confirm by hand a transfer the bank accepted (Sent) that the statement did not match. Not an unknown
        outcome (the bank may not have it: recover it) and not an unsigned document (nobody released it)."""
        self.check_access('write')
        self._gec_bank_check_user(code)
        for payment in self._gec_bank_own(code).filtered(lambda p: p.gec_bank_state == 'sent'):
            payment._gec_bank_write_result({'gec_bank_state': 'confirmed', 'gec_bank_confirmed_source': 'manual'})
            payment.message_post(body=_("%(bank)s transfer manually confirmed by %(user)s.",
                                        bank=payment._gec_bank_label(), user=self.env.user.name))
        return True

    def _gec_bank_refresh_status(self, code):
        self.check_access('write')
        for payment in self._gec_bank_own(code):
            payment._gec_bank_refresh_one()
        return True

    @api.model
    def _gec_bank_poll_status(self, code, connection_field, order):
        """Refresh one bank's open transfers, at most GEC_BANK_STATUS_POLL_LIMIT per run in ``order``. Only journals
        whose ``connection_field`` connection is usable are polled ('error' included: one failed login must not stop
        the poll for good)."""
        journals = self.env['account.journal'].with_context(active_test=False).search([('type', '=', 'bank')])
        journals = journals.filtered(lambda journal: journal[connection_field].state in ('active', 'error'))
        payments = self.search([
            ('payment_method_id.code', '=', code),
            ('gec_bank_state', 'in', list(self._gec_bank_state_groups()['open'])),
            ('gec_bank_reference', '!=', False),
            ('journal_id', 'in', journals.ids),
        ], order=order, limit=GEC_BANK_STATUS_POLL_LIMIT)
        for payment in payments.with_context(gec_bank_poll=True):
            try:
                with self.env.cr.savepoint():
                    payment._gec_bank_refresh_one()
            except Exception:
                _logger.exception("%s: status refresh failed for payment %s", code, payment.id)

    def _gec_bank_revoke_approval(self, reset_state):
        """Void an approval after approved content changed, forcing re-approval. Always cleared (approver saw
        other instructions); a transfer not yet at the bank also goes to ``reset_state``."""
        groups = self._gec_bank_state_groups()
        to_reset = self.filtered(lambda p: p.gec_bank_state in groups['in_approval'])
        to_clear = self.filtered(
            lambda p: p.gec_bank_approved_by and p.gec_bank_state not in groups['at_bank']) - to_reset
        if to_reset:
            to_reset._gec_bank_internal_write({'gec_bank_state': reset_state,
                                               'gec_bank_approved_by': False,
                                               'gec_bank_approved_date': False})
            for payment in to_reset:
                payment.message_post(body=_("The approval was reset because the amount, recipient or "
                                            "purpose changed after approval. Submit it for approval "
                                            "again before sending."))
        if to_clear:
            to_clear._gec_bank_internal_write({'gec_bank_approved_by': False, 'gec_bank_approved_date': False})

    def write(self, vals):
        """Void the approval and record who changed what a transfer is built from (maker is not checker); a new
        bank starts clean (_gec_bank_release_bank); a payment held unbooked cannot change batch."""
        if ('batch_payment_id' in vals
                and self.env.context.get('gec_bank_write_token') is not GEC_BANK_WRITE_TOKEN):
            self.filtered(lambda p: p.batch_payment_id.id != vals['batch_payment_id'])._gec_bank_check_not_held()
        changed = self.filtered(lambda p: p.gec_bank_code and p._gec_bank_payload_fields() & set(vals))
        if changed:
            changed._gec_bank_revoke_approval('pending')
        old_codes = ({payment: payment.gec_bank_code for payment in self}
                     if {'payment_method_line_id', 'journal_id', 'payment_type'} & set(vals) else {})
        res = super().write(vals)
        if changed:
            changed._gec_bank_internal_write({'gec_bank_prepared_by': self.env.uid})
        if old_codes:
            self.filtered(lambda p: p.gec_bank_code != old_codes[p])._gec_bank_release_bank(old_codes)
        return res

    def _gec_bank_release_bank(self, old_codes):
        """Clear a moved payment's transfer values so the new bank never reuses the old request id,
        reference or approval; the old values are posted first. Only a payment not at the bank can move."""
        blocked = self._gec_bank_state_groups()['at_bank'] | {'unknown'}
        for payment in self:
            if payment.gec_bank_state in blocked:
                raise UserError(_("%s is at the bank, or may be, so it cannot move to another bank "
                                  "or payment method.", payment.display_name))
            if not (payment.gec_bank_request_id or payment.gec_bank_reference or payment.gec_bank_approved_by
                    or payment.gec_bank_error or payment.gec_bank_state not in (False, 'pending')):
                continue
            payment.message_post(body=Markup("%s<br/>%s") % (
                _("This payment moved from %(old)s to %(new)s. The earlier transfer's values were cleared:",
                  old=self._gec_bank_label_for(old_codes[payment]),
                  new=self._gec_bank_label_for(payment.gec_bank_code) if payment.gec_bank_code else _("no bank")),
                _("state %(state)s, reference %(reference)s, request id %(request)s, approved by %(approver)s",
                  state=payment.gec_bank_state or '-', reference=payment.gec_bank_reference or '-',
                  request=payment.gec_bank_request_id or '-',
                  approver=payment.gec_bank_approved_by.display_name or '-')))
            payment._gec_bank_internal_write({
                'gec_bank_state': 'pending' if payment.gec_bank_code else False,
                'gec_bank_reference': False, 'gec_bank_request_id': False, 'gec_bank_error': False,
                'gec_bank_approved_by': False, 'gec_bank_approved_date': False,
                'gec_bank_confirmed_source': False,
            })
