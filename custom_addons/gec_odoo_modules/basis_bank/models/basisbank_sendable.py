from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BasisbankSendable(models.AbstractModel):
    """Shared by Basis payments and batches: approved once, sent with the sender's OTP.
    The models keep ``basisbank_state`` and ``basisbank_approval_id``."""

    _name = 'basisbank.sendable'
    _description = 'Basis Bank Sendable Mixin'
    _inherit = 'gec.bank.sendable'

    basisbank_approved_by = fields.Many2one('res.users', string='Basis Bank Approved By', readonly=True, copy=False)
    basisbank_approved_date = fields.Datetime(string='Basis Bank Approved On', readonly=True, copy=False)
    basisbank_sent_date = fields.Datetime(string='Sent to Basis Bank On', readonly=True, copy=False)
    basisbank_bank_response = fields.Text(string='Basis Bank Answer', readonly=True, copy=False)

    @api.depends('basisbank_approval_id', 'basisbank_approval_id.approver_id', 'basisbank_approval_id.delegate_ids')
    def _compute_basisbank_can_approve(self):
        """Whether the current user may approve, by the same rule as the Approve click; sudo-read so it never raises on non-Basis records."""
        user = self.env.user
        for record in self:
            approval = record.basisbank_approval_id
            makers = record.create_uid
            if 'gec_bank_prepared_by' in record._fields:
                makers |= record.gec_bank_prepared_by
            self_approval = record.journal_id.basisbank_connection_id.sudo().allow_self_approval
            record.basisbank_can_approve = bool(approval) and approval.sudo().user_can_approve(user) and (user not in makers or self_approval)

    def _basisbank_connection(self):
        """Return the journal's active Basis Bank connection, or raise if missing or blocked."""
        self.ensure_one()
        connection = self.journal_id.basisbank_connection_id
        errors = connection._gec_bank_unusable_errors(self.journal_id.company_id)
        if errors:
            raise UserError(errors[0])
        return connection

    def _basisbank_request_approval(self, connection, body):
        """Move to Awaiting Approval and tell the connection's approvers."""
        self.ensure_one()
        self._gec_bank_internal_write({'basisbank_state': 'awaiting_approval'})
        recipients = connection.approval_id.approver_user_ids().partner_id
        self.message_subscribe(partner_ids=recipients.ids)
        self.message_post(body=body, partner_ids=recipients.ids)

    def action_basisbank_approve(self):
        """Approve what awaits approval; it then waits for the sender's OTP.
        Only an approver of the journal's connection who did not create it, unless self-approval is allowed."""
        for record in self:
            if record.basisbank_state != 'awaiting_approval':
                raise UserError(_("Only transfers awaiting approval can be approved."))
            connection = record._basisbank_connection()
            connection.approval_id._gec_bank_check_approver(record, connection.allow_self_approval, connection._gec_bank_label())
            record._gec_bank_internal_write({
                'basisbank_state': 'awaiting_otp',
                'basisbank_approved_by': self.env.user.id,
                'basisbank_approved_date': fields.Datetime.now(),
            })
            record.message_post(body=_("Approved for Basis Bank by %s.", self.env.user.display_name))
        return True

    def _basisbank_check_approved(self, connection):
        """Where Odoo approves, refuse a send that was not approved, or whose approver may no longer approve."""
        self.ensure_one()
        if connection.processing_mode != 'odoo_approve':
            return
        if self.basisbank_state != 'awaiting_otp':
            raise UserError(_("This transfer must be approved in Odoo before it can be sent."))
        approval = self.basisbank_approval_id
        if not self.basisbank_approved_by or not (approval and approval.user_can_approve(self.basisbank_approved_by)):
            raise UserError(_("This transfer was not approved by an authorized approver. Have an approver approve it before sending."))

    def _basisbank_ensure_session(self, connection):
        """Log in again when the bank session expired, before anything is claimed."""
        if not connection.ticket_is_valid() and not self.env['basisbank.service'].authenticate(connection):
            raise UserError(_("Could not authenticate with Basis Bank: %s") % (connection.sudo().last_error_message or _("check the connection.")))

    def _basisbank_otp_dialog(self, field_name):
        """The dialog asking the sender for the Digipass code; ``field_name`` links it to this record."""
        self.ensure_one()
        return {
            'name': _("Enter OTP"),
            'type': 'ir.actions.act_window',
            'res_model': 'basisbank.otp.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_%s' % field_name: self.id},
        }

    def _basisbank_revoke_approval(self, reset_state):
        """Void an in-flight approval after approved content changed; force re-approval."""
        to_reset = self.filtered(lambda r: r.basisbank_state in ('awaiting_approval', 'awaiting_otp'))
        if not to_reset:
            return
        to_reset._gec_bank_internal_write({
            'basisbank_state': reset_state,
            'basisbank_approved_by': False,
            'basisbank_approved_date': False,
        })
        for record in to_reset:
            record.message_post(body=_("The approval was reset because the amount, recipient or purpose changed after approval. Submit it for "
                "approval again before sending."))

    def _basisbank_notify(self, message, level):
        return self._gec_bank_notify(_("Basis Bank"), message, level)
