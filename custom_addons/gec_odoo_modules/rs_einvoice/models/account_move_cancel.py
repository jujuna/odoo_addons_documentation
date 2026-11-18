import logging
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _rs_schedule_manual_reversal_activity(self, reason='', note=None):
        """Crons run as OdooBot, so there the TODO goes to the responsible user."""
        self.ensure_one()
        doc = self._rs_doc_label()
        user = self.env.user
        if user._is_superuser():
            user = self.invoice_user_id or self.create_uid or user
        try:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_(
                    "rs.ge cancellation accepted — %s needs manual "
                    "cancellation"
                ) % doc,
                note=note or _(
                    "rs.ge cancelled this document but Odoo could not "
                    "auto-cancel the local %(doc)s.\nReason: %(reason)s\n\n"
                    "Open it, fix the blocker (unreconcile payments, ask "
                    "the accountant to open a locked period), then Reset "
                    "to Draft and Cancel so the books match rs.ge."
                ) % {'doc': doc, 'reason': reason or _('see RS Logs')},
                user_id=user.id,
            )
        except Exception:
            _logger.exception("Could not schedule manual-cancel activity on move %s", self.id)

    def _rs_flag_manual_reversal(self, reason, note=None):
        """The TODO and chatter post happen once, so activities do not stack."""
        self.ensure_one()
        self._rs_log("rs.ge voided or superseded this document, but Odoo did not cancel it: %s" % reason, 'error')
        if self.rs_einv_reversal_pending_at:
            return
        self.rs_einv_reversal_pending_at = fields.Datetime.now()
        self._rs_schedule_manual_reversal_activity(reason=reason, note=note)
        self._rs_post(_("rs.ge voided or superseded this %(doc)s, but Odoo "
            "did not cancel it: %(reason)s. See the To-Do activity.") % {'doc': self._rs_doc_label(), 'reason': reason})

    def _rs_auto_cancel_after_rs_cancellation(self, event_message=None):
        """Mirrors an rs.ge voiding (status 7; 8 on a corrected original). True once cancelled or reversed;
        False is flagged for manual action and retried by Check Status."""
        self.ensure_one()
        if self.payment_state == 'reversed':
            self.rs_einv_reversal_pending_at = False
            self._rs_log("rs.ge voided or superseded this document; its credit notes already reverse it in full, so it was left as it is.")
            return True
        if self.payment_state != 'not_paid':
            self._rs_flag_manual_reversal(
                _("payments or credit notes are applied (payment status: %s)")
                % self._rs_field_label(self, 'payment_state'),
                note=_(
                    "rs.ge voided or superseded this %(doc)s, but payments or "
                    "credit notes are applied to it, so Odoo did not cancel it: "
                    "cancelling would unreconcile them.\n\n"
                    "1. Unreconcile the payments on this %(doc)s. For a credit note "
                    "applied to it, either reset that credit note to draft and cancel "
                    "it, or credit the rest of this %(doc)s so it is fully reversed.\n"
                    "2. Click Check Status: Odoo then cancels it to match rs.ge, or "
                    "leaves it as it is when credit notes fully reverse it.\n"
                    "3. Apply the freed payment to the replacement or another "
                    "open %(doc)s, or refund it."
                ) % {'doc': self._rs_doc_label()},
            )
            return False
        open_refunds = self.reversal_move_ids.filtered(lambda refund: refund.state != 'cancel')
        if open_refunds:
            names = ', '.join(open_refunds.mapped('display_name'))
            self._rs_flag_manual_reversal(
                _("credit notes are linked to it (%s)") % names,
                note=_(
                    "rs.ge voided or superseded this %(doc)s, but credit notes "
                    "are linked to it (%(names)s), so Odoo did not cancel it: "
                    "they would stay open.\n\n"
                    "1. Delete a draft credit note. For a posted one, either reset "
                    "it to draft and cancel it, or credit the rest of this %(doc)s "
                    "so it is fully reversed.\n"
                    "2. Click Check Status: a %(doc)s fully reversed by its "
                    "credit notes is left as it is, otherwise Odoo cancels it. "
                    "If rs.ge shows it rejected rather than cancelled, reset it "
                    "to draft and cancel it yourself."
                ) % {'doc': self._rs_doc_label(), 'names': names},
            )
            return False
        reversal = self.env['account.move']
        try:
            with self.env.cr.savepoint():
                move = self.with_context(rs_skip_lock_check=True)
                if move.state == 'posted' and move._rs_is_prior_vat_period():
                    reversal = move._rs_reverse_in_current_period()
                else:
                    if move.state == 'posted':
                        move.button_draft()
                    move.button_cancel()
        except (UserError, ValidationError) as e:
            self._rs_flag_manual_reversal(str(e))
            return False
        except Exception as e:
            _logger.exception("Auto-cancel CRASHED on move %s (rs_id=%s): %s", self.id, self.rs_einv_id, e)
            self._rs_flag_manual_reversal(str(e))
            return False

        self.rs_einv_reversal_pending_at = False
        if reversal:
            self._rs_log("Reversed by credit note %s dated %s to mirror rs.ge: this document belongs to an earlier VAT period, so it was not "
                "cancelled." % (reversal.name, reversal.date))
            self._rs_post(_("rs.ge no longer counts this %(doc)s. It belongs to an earlier VAT period, so Odoo reversed it with credit note "
                "%(credit_note)s dated today instead of "
                "cancelling it; the declared period stays unchanged.") % {'doc': self._rs_doc_label(), 'credit_note': reversal.name})
            return True
        self._rs_log("Auto-cancelled to mirror rs.ge state change.")
        self._rs_post(event_message or _("rs.ge cancellation accepted — this %s has been automatically set to Cancelled.") % self._rs_doc_label())
        return True

    def _rs_is_prior_vat_period(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        return bool((self.date.year,
            self.date.month) < (today.year, today.month) or self.company_id._get_violated_lock_dates(self.date, True, self.journal_id))

    def _rs_reverse_in_current_period(self):
        """Credit note dated today, marked Skip rs.ge: never filed, cannot be reset to draft."""
        self.ensure_one()
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=self.ids,
        ).create({
            'journal_id': self.journal_id.id,
            'reason': _("rs.ge no longer counts this document"),
            'rs_einv_flow': 'skip',
            'rs_einv_skip_reason_choice': 'replacement',
        })
        reversal = self._reverse_moves([{'partner_bank_id': False, **wizard._prepare_default_reversal(self)}], cancel=True)
        return reversal

    def _rs_post_accepted_correction(self):
        """Posts a seller correction dated today once the buyer accepted it; False keeps its original untouched, a bill is never posted here."""
        self.ensure_one()
        if self.state != 'draft' or not self._rs_is_sale_correction():
            return True
        if self.rs_einv_has_pending_changes:
            reason = _("its lines changed after the correction was sent")
        else:
            try:
                with self.env.cr.savepoint():
                    if not self.posted_before:
                        self.write({'date': fields.Date.context_today(self)})
                    self.with_context(rs_post_accepted_correction=True).action_post()
                return True
            except (UserError, ValidationError) as e:
                reason = str(e)
        summary = _("Post the correction accepted on rs.ge")
        langs = [code for code, _label in self.env['res.lang'].get_installed()]
        summaries = {self.with_context(lang=code).env._("Post the correction accepted on rs.ge") for code in langs}
        if self.activity_ids.filtered(lambda activity: activity.summary in summaries):
            return False
        self._rs_notify(_("%(name)s was accepted on rs.ge but Odoo did not post it: %(reason)s. Fix the cause and click Check Status to retry.",
            name=self.display_name, reason=reason), 'warning', post_chatter=True, activity_xmlid='mail.mail_activity_data_todo',
            activity_summary=summary)
        return False

    def _rs_neutralize_after_correction_accepted(self):
        """Check Status retries it on each refresh; True once the original is cancelled or reversed."""
        self.ensure_one()
        if (self.move_type not in ('out_invoice', 'in_invoice') or self.state != 'posted' or self.payment_state == 'reversed'):
            return False
        done = self._rs_auto_cancel_after_rs_cancellation(event_message=_("Correction accepted on rs.ge — this %s was superseded by the corrected "
            "invoice and has been set to Cancelled.") % self._rs_doc_label())
        replacement = self.rs_einv_replaced_by_id
        if done and replacement.state == 'draft' and replacement.move_type == 'in_invoice':
            replacement.date = fields.Date.context_today(self)
        return done

    def _rs_release_stranded_replacement(self):
        """Buyer refused the original's cancellation, so its replacement draft would stay counted as invoiced."""
        self.ensure_one()
        replacement = self.rs_einv_replaced_by_id
        if (not replacement or replacement.state == 'cancel' or replacement.rs_einv_replacement_mode != 'fresh'):
            return
        reason = _("it is already posted or on rs.ge")
        if replacement.state == 'draft' and not replacement.rs_einv_id:
            try:
                with self.env.cr.savepoint():
                    replacement.button_cancel()
                    replacement._rs_log("Cancelled automatically: the buyer refused the cancellation of %s on rs.ge, so this replacement is not "
                        "needed." % (self.display_name or self.name))
                    self.action_rs_clear_cancelled_replacement_link()
                return
            except (UserError, ValidationError) as e:
                reason = str(e)
        self._rs_notify(_("The buyer refused the cancellation on rs.ge, so replacement %(name)s is not needed, but Odoo could not cancel it "
            "(%(reason)s). Cancel or delete it manually.") % {'name': replacement.display_name or '—', 'reason': reason}, 'warning',
            post_chatter=True, activity_xmlid='mail.mail_activity_data_todo', activity_summary=_("Cancel the unused replacement invoice"))

    def _rs_reset_correction_to_draft_after_rejection(self):
        """Buyer rejected the correction (status back to 4); reset to draft to re-send on the same rs.ge record."""
        self.ensure_one()
        if self.state != 'posted':
            return
        try:
            self.with_context(rs_skip_lock_check=True).button_draft()
        except (UserError, ValidationError) as e:
            self._rs_log("Correction rejected but could not auto-reset to draft: %s. Reset it to draft manually to edit and re-send." % e, 'warning')
            self._rs_schedule_manual_reversal_activity(reason=str(e))
            return
        self._rs_log("Correction rejected on rs.ge — reset to draft. Edit the lines, then click 'Update on RS' and 'Send to buyer' to re-file on "
            "the same rs.ge record; Odoo posts it when the buyer accepts.")

    def _rs_schedule_cancel_pending_activity(self, target_id):
        self.ensure_one()
        self.rs_einv_cancel_pending_at = fields.Datetime.now()
        msg = _("Cancellation request sent to rs.ge for record %(rs_id)s. Odoo accounting is not reversed yet — reversal happens only after the "
            "buyer confirms the cancellation on rs.ge.") % {'rs_id': target_id or self.rs_einv_id or '—'}
        self._rs_notify(msg, 'warning', post_chatter=True, activity_xmlid='mail.mail_activity_data_todo',
            activity_summary=_("Waiting for buyer to confirm rs.ge cancellation"), activity_deadline=fields.Date.today() + timedelta(days=14))

    def _rs_schedule_line_sync_activity(self, target_id, failed_line, committed_writes, total_lines):
        self.ensure_one()
        msg = _("Line sync to rs.ge stopped at '%(line)s' for record %(rs_id)s. %(done)s of %(total)s line slot(s) were already written, so rs.ge "
            "may hold a mix of old and new lines. Fix the issue and click Update on RS before sending to "
            "the buyer.") % {'line': failed_line or '—', 'rs_id': target_id or self.rs_einv_id or '—', 'done': committed_writes, 'total': total_lines}
        self._rs_notify(msg, 'error', post_chatter=True, activity_xmlid='mail.mail_activity_data_todo',
            activity_summary=_("rs.ge line sync incomplete"))
