from odoo import _, api, models

GEC_BANK_HANDOFF_STATES = frozenset({
    'pending', 'prepared', 'partial', 'transmitted', 'confirmed', 'failed', 'uncertain',
})
# Bank state of a transfer-flow payment -> its handoff state for the payroll watchdog.
# 'sending' is uncertain: a send ends within a minute, so a payment still sending crashed mid-call.
GEC_BANK_TRANSFER_HANDOFF = {
    'pending': 'prepared',
    'awaiting_approval': 'prepared',
    'approved': 'prepared',
    'sending': 'uncertain',
    'sent': 'transmitted',
    'confirmed': 'confirmed',
    'failed': 'failed',
    'unknown': 'uncertain',
}
# Field domain of a channel picker on a record with ``company_id``; Python form: ``_gec_bank_channel_domain``.
GEC_BANK_CHANNEL_DOMAIN = (
    "[('payment_type', '=', 'outbound'), ('journal_id.type', '=', 'bank'),"
    " ('journal_id', '!=', False), ('company_id', '=', company_id)]"
)


def bic_prefix(bic):
    """The bank part of a BIC: its first 8 characters, without the branch suffix."""
    return (bic or '').strip().upper()[:8]


class AccountPaymentMethodLine(models.Model):
    """A bank channel: a bank journal's payment method line that payments are handed to. The hooks are the
    contract between bank modules and callers such as Pay Salaries; without a bank module the defaults
    answer."""

    _inherit = 'account.payment.method.line'

    def _gec_bank_transfer_flow(self):
        """True when this channel's payments run account.payment's shared transfer flow; a bank opts its code in."""
        self.ensure_one()
        return False

    def _gec_bank_channel_kind(self):
        """How money leaves this channel: 'api', 'file' or 'manual'; file methods come from the batch-payment registry.
        Override: guard on ``self.code``, return 'api' for your own code, else super()."""
        self.ensure_one()
        if self.code in self.env['account.batch.payment']._get_methods_generating_files():
            return 'file'
        return 'manual'

    def _gec_bank_check(self, kind, lines):
        """Return blocking messages for this channel; override: super() first, guard on ``self.code``, then
        append. ``kind`` is 'salary' or 'authority'; ``lines`` is an ``account.move.line`` recordset."""
        return []

    def _gec_bank_payment_vals(self, kind, payment):
        """Return values to write on one freshly created payment of this channel; override: super() first,
        guard on code. The payment is already posted and reconciled: no field of
        ``_get_trigger_fields_to_synchronize()`` or ``payment_method_line_id``."""
        return {}

    def _gec_bank_batch_vals(self, kind):
        """Return extra values merged into the batch create vals; caller-owned keys are reserved.
        Override: super() first, guard on ``self.code``."""
        return {}

    def _gec_bank_handoff_state(self, batch):
        """Where the batch stands with the bank: one of ``GEC_BANK_HANDOFF_STATES``; override: guard on code,
        else super(). Return 'uncertain' when a send timed out or crashed (payroll says resync, not
        reverse); no network I/O (cron)."""
        self.ensure_one()
        if self._gec_bank_transfer_flow():
            return self._gec_bank_merge_handoff_states(self._gec_bank_transfer_handoff_states(batch))
        return 'prepared' if batch.state == 'draft' else 'transmitted'

    def _gec_bank_handoff_map(self):
        """Bank state -> handoff state for this transfer-flow channel; a bank adds its own."""
        return dict(GEC_BANK_TRANSFER_HANDOFF)

    def _gec_bank_transfer_handoff_states(self, batch):
        """The handoff state of each payment of a batch, so one rejected salary never hides behind a sent batch."""
        mapping = self._gec_bank_handoff_map()
        return {mapping.get(state, 'uncertain') for state in batch.payment_ids.mapped('gec_bank_state')}

    @api.model
    def _gec_bank_merge_handoff_states(self, states):
        """One handoff state for a batch from its payments' states: failed wins (partial if others did not fail),
        then uncertain, then not yet at the bank; confirmed only when all are."""
        if 'failed' in states:
            return 'failed' if states == {'failed'} else 'partial'
        for state in ('uncertain', 'prepared', 'pending', 'transmitted'):
            if state in states:
                return state
        return 'confirmed' if states else 'prepared'

    def _gec_bank_config_errors(self):
        """Configuration problems that make this channel unusable.
        Do not override: add bank checks in ``_gec_bank_extra_config_errors``."""
        self.ensure_one()
        return self._gec_bank_core_config_errors() + self._gec_bank_extra_config_errors()

    def _gec_bank_extra_config_errors(self):
        """Extra channel-configuration problems. Override: call super() first."""
        return []

    def _gec_bank_core_config_errors(self):
        """Checks every channel must pass; an API channel also needs the sender IBAN on the journal."""
        self.ensure_one()
        errors = []
        name = self.display_name
        if self.payment_type != 'outbound':
            errors.append(_("%s is not an outbound payment method.", name))
        if self.journal_id.type != 'bank':
            errors.append(_("%s is not on a bank journal.", name))
        account = self.payment_account_id
        if not account:
            errors.append(_(
                "%s has no Outstanding Payments account, so its payments would post "
                "no journal entry at all.", name))
        else:
            if account.account_type in ('asset_cash', 'liability_credit_card'):
                errors.append(_(
                    "The Outstanding Payments account of %s is a bank/cash account, so "
                    "payments would be marked paid before the bank confirms them.", name))
            elif not account.reconcile:
                errors.append(_(
                    "The Outstanding Payments account of %s must allow reconciliation.", name))
            if account == self.journal_id.default_account_id:
                errors.append(_(
                    "The Outstanding Payments account of %s is the journal's own account; "
                    "payments would never wait for the bank statement.", name))
        if (self._gec_bank_channel_kind() == 'api'
                and not (self.journal_id.bank_account_number or '').strip()):
            errors.append(_("%s has no IBAN, so the bank cannot identify the sender.",
                            self.journal_id.display_name))
        return errors

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._gec_bank_fill_outstanding()
        return lines

    def _gec_bank_fill_outstanding(self):
        """Give an API channel core's default Outstanding Payments account, which core leaves empty
        (``_gec_bank_core_config_errors`` refuses a channel without it)."""
        for line in self.filtered(lambda line: not line.payment_account_id
                                  and line.payment_type == 'outbound'
                                  and line._gec_bank_channel_kind() == 'api'):
            account = line.journal_id._gec_bank_default_outstanding_account()
            if account:
                line.payment_account_id = account

    @api.model
    def _gec_bank_channel_domain(self, company):
        return [
            ('payment_type', '=', 'outbound'),
            ('journal_id.type', '=', 'bank'),
            ('journal_id', '!=', False),
            ('company_id', '=', company.id),
        ]
