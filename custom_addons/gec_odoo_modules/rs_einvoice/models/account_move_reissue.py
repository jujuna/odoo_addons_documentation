from odoo import fields, models, _
from odoo.exceptions import UserError

from .account_move import K_TYPE, RS_CONFIRMED
from .account_move_seller import RsNoAnswerError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _rs_assert_replacement_cancel_accepted(self):
        """Blocks until the buyer confirms the cancellation (7), else two invoices stay live; corrections skip it."""
        self.ensure_one()
        original = self.rs_einv_replaces_id
        if not original:
            return
        if self.rs_einv_replacement_mode == 'correction':
            return
        if original.rs_einv_id and original.rs_einv_status != '7':
            original._rs_safe_refresh_status()
        if original.rs_einv_status == '7':
            return
        raise UserError(_(
            "Cannot post or send this replacement invoice yet.\n\n"
            "Cancel-and-Reissue first sends a cancellation request for the "
            "original on rs.ge; the buyer must confirm that cancellation "
            "(rs.ge status 7) before the replacement can be sent as a new "
            "invoice.\n\n"
            "Original %(name)s is at rs.ge status '%(status)s' (ID %(rs_id)s). "
            "Wait for the buyer to confirm the cancellation, click 'Check "
            "Status' on the original, then post and send this replacement.",
            name=original.display_name or original.name or '-',
            status=original.rs_einv_status or '-',
            rs_id=original.rs_einv_id or '-',
        ))

    def _rs_replace_preflight(self):
        self.ensure_one()
        if self.move_type != 'out_invoice':
            raise UserError(_("Cancel & Reissue and Correct & Reissue are seller-side only. For supplier corrections, use Import Supplier Correction "
                "from the buyer-side rs.ge flow."))
        if self.state != 'posted':
            raise UserError(_("Only posted invoices can be replaced. Post the invoice first, or edit the draft directly if it has not been posted "
                "yet."))
        if self.rs_einv_skip:
            raise UserError(_("This invoice is marked Skip rs.ge, so there is no rs.ge invoice to replace."))
        if not self.rs_einv_id:
            raise UserError(_("This invoice has not been sent to rs.ge yet. Edit it locally or send it to rs.ge before using Cancel & Reissue or "
                "Correct & Reissue."))
        if self.rs_einv_status not in RS_CONFIRMED:
            raise UserError(_("Cancel & Reissue and Correct & Reissue can only start from a confirmed rs.ge invoice (status 2) or confirmed "
                "correction (status 8). Current status: '%s'. Finish, delete, or refresh the current rs.ge state first.", self.rs_einv_status or '-'))
        if self.rs_einv_is_advance:
            raise UserError(_("Advance invoices are not replaced. Use Add Credit Note with a full-cancellation reason for the advance reversal, then "
                "issue the new final invoice separately."))
        if self.rs_einv_replaced_by_id:
            if self.rs_einv_replaced_by_id.state == 'cancel':
                raise UserError(_("This invoice is linked to cancelled replacement %s. Use 'Clear Cancelled Replacement' before starting a new "
                    "reissue flow.", self.rs_einv_replaced_by_id.display_name))
            raise UserError(_("This invoice has already been replaced by %s. Open that replacement invoice if another correction is needed.",
                self.rs_einv_replaced_by_id.display_name))
        blocker = self._rs_find_pending_correction_blocker()
        if blocker:
            raise UserError(_(
                "Cannot reissue this invoice because another correction "
                "is still in flight on rs.ge:\n"
                "  - Document: %s\n"
                "  - rs.ge ID: %s\n"
                "  - Status: %s\n\n"
                "Send it to the buyer and wait for acceptance, or delete "
                "it on rs.ge, then try again.",
                blocker.display_name or blocker.name or '-',
                blocker.rs_einv_id or '-',
                blocker.rs_einv_status or '-',
            ))

    def _rs_do_cancel_reissue(self):
        """Sends a real rs.ge cancellation (2/8 -> 6 -> 7) for a wrong buyer or duplicate; content errors use
        _rs_do_correct_reissue. The original is cancelled only when the buyer confirms (7), not here.
        The replacement is copied first, so a failed copy never reaches rs.ge."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Cancel and Reissue'))
        self._rs_replace_preflight()
        self._rs_safe_refresh_status()
        self._rs_replace_preflight()
        new_invoice = self.with_context(include_business_fields=True).copy({
            'rs_einv_replaces_id': self.id,
            'rs_einv_replacement_mode': 'fresh',
            'rs_einv_advance_settlement_mode': self.rs_einv_advance_settlement_mode,
            'invoice_origin': self.invoice_origin,
            'invoice_date': fields.Date.context_today(self),
            'date': fields.Date.context_today(self),
            'ref': _('Replacement of %s') % (self.name or self.display_name),
        })
        self.rs_einv_replaced_by_id = new_invoice.id
        new_invoice._rs_log("Created as Cancel-and-Reissue replacement for %s. Post and edit this invoice; it will be sent to rs.ge as a new, "
            "separate invoice once the buyer confirms the cancellation of the original." % (self.display_name or self.name,))
        self.env.cr.commit()
        try:
            self._rs_acquire_row_lock(_('Cancel and Reissue'))
            self._rs_cancel_core()
        except RsNoAnswerError:
            raise
        except Exception:
            self.env.cr.rollback()
            self.rs_einv_replaced_by_id = False
            new_invoice.unlink()
            self.env.cr.commit()
            raise
        self.env.cr.commit()

        self._rs_log("Cancel-and-Reissue flow started. A cancellation request was sent to rs.ge for this invoice (no correction type); draft "
            "replacement invoice %s created. The replacement is blocked from "
            "sending until the buyer confirms the cancellation on rs.ge (status 7)." % (new_invoice.display_name or new_invoice.name,))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Replacement Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': new_invoice.id,
            'context': {'default_move_type': 'out_invoice'},
        }

    def _rs_do_correct_reissue(self, k_type=None):
        """The original stays live until the buyer accepts the correction (8); a rejected correction can be re-sent."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Correct and Reissue'))
        self._rs_replace_preflight()
        self._rs_safe_refresh_status()
        self._rs_replace_preflight()
        self._rs_assert_advance_correctable(self._rs_get_service())

        chosen_k_type = str(k_type or '3')
        if chosen_k_type not in self._rs_correction_k_types():
            raise UserError(_("Invalid rs.ge correction reason: %s") % chosen_k_type)

        new_invoice = self.with_context(include_business_fields=True).copy(self._rs_correction_copy_vals(chosen_k_type))
        self.rs_einv_replaced_by_id = new_invoice.id

        self._rs_log("Correct-and-Reissue started. Draft corrected invoice %s created. This invoice stays active until the buyer accepts the "
            "correction on rs.ge; it is then cancelled automatically so the books show only the corrected invoice. Edit the draft and click "
            "'Send to RS' without posting it." % (new_invoice.display_name or new_invoice.name,))
        new_invoice._rs_log("Created as Correct-and-Reissue replacement for %s. Send it to rs.ge as a draft; Odoo posts it, dated that day, when "
            "the buyer accepts, and cancels the original then." % (self.display_name or self.name,))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Correction-Replacement Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': new_invoice.id,
            'context': {'default_move_type': 'out_invoice'},
        }

    def _rs_correction_k_types(self):
        return [code for code, _label in K_TYPE]

    def _rs_correction_copy_vals(self, k_type):
        return {
            'rs_einv_replaces_id': self.id,
            'rs_einv_replacement_mode': 'correction',
            'rs_einv_advance_settlement_mode': self.rs_einv_advance_settlement_mode,
            'rs_einv_k_type': k_type,
            'invoice_origin': self.invoice_origin,
            'invoice_date': fields.Date.context_today(self),
            'date': fields.Date.context_today(self),
            'ref': _('Correction-replacement of %s') % (self.name or self.display_name),
        }

