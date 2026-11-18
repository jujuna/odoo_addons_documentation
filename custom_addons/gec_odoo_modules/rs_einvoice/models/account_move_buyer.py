import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import models, fields, Command, _
from odoo.exceptions import UserError, ValidationError

from .account_move import _rs_clean_number, _rs_status_label, RS_BUYER_ACTIONABLE, RS_CONFIRMED, RS_PENDING_BUYER

_logger = logging.getLogger(__name__)
_RS_BUYER_ACCEPT_TARGETS = {'1': 2, '5': 8, '6': 7}
# A younger marker may still have its SOAP write in flight; clearing it could let a re-send duplicate.
_RS_PENDING_DISMISS_MIN_AGE_MINUTES = 5


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_rs_buyer_pull(self):
        """Bill date and status are written together: write() locks the date once a status is set."""
        self.ensure_one()
        if not self.rs_einv_is_buyer_side:
            raise UserError(_("Pull from rs.ge only applies to vendor bills and vendor credit notes."))
        if not self.rs_einv_id:
            raise UserError(_("Paste the RS Invoice ID the supplier sent you in the 'RS Invoice ID (from supplier)' field, then click Pull from "
                "rs.ge again."))
        if self.rs_einv_skip:
            raise UserError(_("This document is marked 'Skip rs.ge' — uncheck Skip rs.ge "
                "on the RS E-Invoice tab before linking a real rs.ge invoice."))

        service = self._rs_get_service(check_auth=True)
        result = service.get_invoice(self._rs_inv_id_int)
        status = str(getattr(result, 'status', ''))
        if not status or status == '-1':
            raise UserError(_("rs.ge has no usable record for ID %s (status: '%s'). Double-check the ID with the supplier and try again.",
                self.rs_einv_id, _rs_status_label(status)))
        if status not in RS_BUYER_ACTIONABLE:
            raise UserError(_(
                "rs.ge ID %s is at status '%s' — the supplier has not yet "
                "sent this document to you on rs.ge. Pulling now would "
                "link a draft they can still edit or delete.\n\n"
                "Ask the supplier to click 'Send to buyer' on rs.ge "
                "(status will change to 'Sent (Pending)' for an original "
                "or 'Correction Sent' for a correction), then pull again.",
                self.rs_einv_id, _rs_status_label(status),
            ))

        self._rs_pull_check_correction_parent(result)
        self._rs_pull_verify_parties(service, result)
        self._rs_pull_apply_header(result, status)
        self._rs_refresh_pulled_lines(service)
        self._rs_log("Pulled vendor invoice from rs.ge (status: %s, series: "
            "%s, number: %s, lines: %d)" % (status, self.rs_einv_series or '—', self.rs_einv_number or '—', len(self.rs_einv_pulled_line_ids)))

        existing_product_lines = self._rs_product_lines()
        if (self.state == 'draft' and not existing_product_lines and self.rs_einv_pulled_line_ids):
            self._rs_auto_import_pulled_to_bill_lines()

    def _rs_pull_check_correction_parent(self, result):
        """A cancelled original passes (cancel-and-reissue); a live one must use Import Supplier Correction."""
        raw_k_id = getattr(result, 'k_id', None)
        try:
            k_id_int = int(raw_k_id) if raw_k_id is not None else 0
        except (TypeError, ValueError):
            k_id_int = 0
        if k_id_int > 0:
            parent_rs_id = str(k_id_int)
            parent = self._rs_find_other_move_by_rs_id(parent_rs_id)
            if parent and parent.state == 'cancel':
                pass
            elif parent:
                raise UserError(_("rs.ge ID %(rs_id)s is a correction of %(parent)s (rs.ge ID %(parent_rs)s). Open that bill and use 'Import "
                    "Supplier Correction' instead.", rs_id=self.rs_einv_id, parent=parent.display_name or parent.name or '—', parent_rs=parent_rs_id))
            else:
                raise UserError(_("rs.ge ID %(rs_id)s is a correction of rs.ge ID %(parent_rs)s, but that original bill is not in Odoo yet. Import "
                    "the original first, then use 'Import Supplier Correction'.", rs_id=self.rs_einv_id, parent_rs=parent_rs_id))

    def _rs_pull_verify_parties(self, service, result, rs_id=None):
        """Refuses a party mismatch, so VAT is not booked against the wrong vendor or buyer."""
        rs_id = rs_id or self.rs_einv_id
        seller_un_id = getattr(result, 'seller_un_id', 0)
        buyer_un_id = getattr(result, 'buyer_un_id', 0)
        try:
            seller_un_id_int = int(seller_un_id or 0)
            buyer_un_id_int = int(buyer_un_id or 0)
        except (TypeError, ValueError):
            raise UserError(_("rs.ge returned unreadable seller/buyer identifiers for ID %s. Odoo cannot safely verify this vendor bill.", rs_id))
        if seller_un_id_int <= 0 or buyer_un_id_int <= 0:
            raise UserError(_("rs.ge did not return both seller and buyer identifiers for ID %s. Odoo cannot safely verify this vendor bill.", rs_id))
        partner_tin = (self.partner_id.vat or '').strip()
        company_tin = (self.company_id.vat or '').strip()
        if not partner_tin:
            raise UserError(_("Vendor '%s' has no TIN/VAT number. Fill it on the partner before pulling from rs.ge.",
                self.partner_id.display_name or '—'))
        if not company_tin:
            raise UserError(_("Company '%s' has no TIN/VAT number. Fill it on the company before pulling from rs.ge.",
                self.company_id.display_name or '—'))
        if not partner_tin.isdigit():
            raise UserError(_("Vendor '%(partner)s' has TIN '%(tin)s'. rs.ge identity checks require digits only.",
                partner=self.partner_id.display_name or '—', tin=partner_tin))
        if not company_tin.isdigit():
            raise UserError(_("Company '%(company)s' has TIN '%(tin)s'. rs.ge identity checks require digits only.",
                company=self.company_id.display_name or '—', tin=company_tin))
        try:
            expected_seller = service._rs_partner_un_id(self.partner_id)
        except Exception as e:
            _logger.warning("Could not resolve un_id for partner TIN %s on bill %s: %s", partner_tin, self.id, e)
            raise UserError(_(
                "Could not verify the supplier identity against rs.ge "
                "(TIN lookup failed for %(tin)s).\n\nDetails: %(err)s"
                "\n\nClick Pull from rs.ge again in a moment — booking VAT "
                "against an unverified supplier is unsafe.",
                tin=partner_tin, err=e,
            ))
        if int(expected_seller) != seller_un_id_int:
            raise UserError(_(
                "The rs.ge record %s belongs to a different supplier than "
                "the partner on this bill.\n\n"
                "Bill partner: %s (TIN %s)\n"
                "rs.ge seller does not match this partner.\n\n"
                "Double-check the rs.ge ID with the supplier before trying again.",
                rs_id,
                self.partner_id.display_name, partner_tin,
            ))
        try:
            expected_buyer = service._rs_company_un_id()
        except Exception as e:
            _logger.warning("Could not resolve un_id for company TIN %s on bill %s: %s", company_tin, self.id, e)
            raise UserError(_(
                "Could not verify your company identity against rs.ge "
                "(TIN lookup failed for %(tin)s).\n\nDetails: %(err)s"
                "\n\nClick Pull from rs.ge again in a moment.",
                tin=company_tin, err=e,
            ))
        if int(expected_buyer) != buyer_un_id_int:
            raise UserError(_("The rs.ge record %s is addressed to a different company. This invoice was not sent to %s (TIN %s) — it cannot be "
                "imported here.", rs_id, self.company_id.display_name, company_tin))

    def _rs_pull_apply_header(self, result, status):
        op_dt = getattr(result, 'operation_dt', None)
        op_date = op_dt.date() if op_dt and hasattr(op_dt, 'date') else False
        vals = {
            'rs_einv_status': status,
            'rs_einv_series': getattr(result, 'f_series', '') or '',
            'rs_einv_number': _rs_clean_number(getattr(result, 'f_number', '')),
        }
        if op_date and self.state == 'draft' and self.invoice_date != op_date:
            vals['invoice_date'] = op_date
        self.write(vals)
        if (op_date and self.state == 'posted' and self.invoice_date != op_date):
            self._rs_log("Pulled rs.ge operation_dt %s does not match this bill's invoice_date %s. Reset to Draft to realign the VAT period before "
                "accepting." % (op_date, self.invoice_date or '—'), 'warning')
        raw_k_type = str(getattr(result, 'k_type', '') or '').strip()
        if raw_k_type in ('1', '2', '3', '4') and not self.rs_einv_k_type:
            self.rs_einv_k_type = raw_k_type


    def action_rs_buyer_reimport_lines(self):
        self.ensure_one()
        if not self.rs_einv_is_buyer_side:
            raise UserError(_("Reimport Lines only applies to vendor bills and vendor credit notes."))
        if self.state != 'draft':
            raise UserError(_("Reset the bill to Draft first — Odoo does not allow line edits on a posted bill."))
        self._rs_refresh_pulled_lines(self._rs_get_service(), raise_on_failure=True)
        if not self.rs_einv_pulled_line_ids:
            raise UserError(_("No rs.ge lines available yet. Click 'Pull from rs.ge' first."))
        self._rs_merge_pulled_to_bill_lines()

    @staticmethod
    def _rs_pulled_match_key(text):
        return (text or '').strip().lower()

    def _rs_purchase_linked_lines(self, lines):
        if 'purchase_line_id' not in lines._fields:
            return lines.browse()
        return lines.filtered('purchase_line_id')

    def _rs_merge_pulled_to_bill_lines(self):
        """PO-linked lines with no rs.ge match stay at qty 0 to keep the order link, as core does."""
        self.ensure_one()
        pulled = self.rs_einv_pulled_line_ids
        if not pulled:
            return
        purchase_vat_18 = self._rs_get_purchase_vat_18()
        self._rs_log_untaxed_pulled_lines(pulled, purchase_vat_18)
        existing_product_lines = self._rs_product_lines()
        snap_by_rs_id = {snap.rs_line_id: snap for snap in pulled if snap.rs_line_id}
        matches = {}
        used = self.env['rs.einvoice.correction.line']
        for line in existing_product_lines:
            snap = snap_by_rs_id.get(line.rs_line_id) if line.rs_line_id else None
            if snap and snap not in used:
                matches[line] = snap
                used |= snap
        for line in existing_product_lines:
            if line in matches:
                continue
            key = self._rs_pulled_match_key(line.name)
            snap = next((s for s in pulled if s not in used and self._rs_pulled_match_key(s.goods) == key), None)
            if snap:
                matches[line] = snap
                used |= snap
        order_lines = self._rs_purchase_linked_lines(existing_product_lines).filtered(lambda line: line not in matches and line.product_id)
        if order_lines:
            product_by_snap = {snap: self._rs_find_product_for_pulled(snap) for snap in pulled - used}
            for line in order_lines:
                snap = next((s for s, product in product_by_snap.items() if s not in used and product == line.product_id), None)
                if snap:
                    matches[line] = snap
                    used |= snap

        unmatched_bill_lines = existing_product_lines.filtered(lambda line: line not in matches)
        built_from_rsge = bool(existing_product_lines.filtered('rs_line_id'))
        for line, snap in matches.items():
            line.write(self._rs_pulled_line_vals(snap, purchase_vat_18, existing_line=line))

        kept_lines = self._rs_purchase_linked_lines(unmatched_bill_lines)
        if kept_lines:
            kept_lines.write({'quantity': 0.0})
            self._rs_log("Reimport (merge): %d bill line(s) linked to a purchase order no longer appear on rs.ge; kept at quantity 0 so the order "
                "link stays: %s" % (len(kept_lines), ', '.join(kept_lines.mapped('name'))[:200]), 'warning')
        unmatched_bill_lines -= kept_lines
        if built_from_rsge:
            own_lines = unmatched_bill_lines.filtered(lambda line: not line.rs_line_id)
            if own_lines:
                self._rs_notify(_("Reimport (merge): kept %d line(s) you added yourself: %s. Check they do not repeat an rs.ge line.",
                    len(own_lines), ', '.join(own_lines.mapped('name'))[:200]), 'warning', post_chatter=True)
            unmatched_bill_lines -= own_lines
        if unmatched_bill_lines:
            self._rs_log("Reimport (merge): removed %d bill "
                "line(s) that no longer appear on rs.ge: %s" % (len(unmatched_bill_lines), ', '.join(unmatched_bill_lines.mapped('name'))[:200]),
                'warning')
            unmatched_bill_lines.unlink()

        new_commands = [Command.create(self._rs_pulled_line_vals(snap, purchase_vat_18)) for snap in pulled - used]
        if new_commands:
            self.write({'invoice_line_ids': new_commands})
            self._rs_log("Reimport (merge): added %d new line(s) from rs.ge." % (len(new_commands),))
        self.rs_einv_pulled_lines_hash = self._rs_pulled_lines_hash()

    def action_rs_buyer_accept(self):
        """A supplier cancellation is cancelled instead of posted, so no number is used and nothing is booked."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Buyer Accept'))
        if not self.rs_einv_is_buyer_side:
            raise UserError(_("Accept on rs.ge only applies to vendor bills and vendor credit notes."))
        if not self.rs_einv_id:
            raise UserError(_("No rs.ge ID linked yet — click 'Pull from rs.ge' first."))

        self._rs_safe_refresh_status()
        if self.state == 'draft' and self.rs_einv_status in RS_CONFIRMED:
            self.with_context(rs_buyer_accept_in_progress=True).action_post()
            return

        target_status = _RS_BUYER_ACCEPT_TARGETS.get(self.rs_einv_status)
        if not target_status:
            raise UserError(_("There is nothing to accept right now. You can confirm rs.ge records that are 'Sent (Pending)', 'Correction Sent' or "
                "'Cancelled (Sent)'. Current status: '%s'.", _rs_status_label(self.rs_einv_status)))
        if self.state == 'cancel':
            raise UserError(_("This bill is cancelled — reset it to draft first if you want to accept on rs.ge."))
        service = self._rs_get_service(check_auth=True)
        if target_status in (2, 8):
            self._rs_refresh_pulled_lines(service, raise_on_failure=True)
        if target_status != 7:
            if self.state == 'draft':
                try:
                    self.with_context(rs_buyer_accept_in_progress=True).action_post()
                except (UserError, ValidationError) as e:
                    raise UserError(_("Could not post the bill before accepting on rs.ge: %s\n\nFix the validation issue and try again.") % e)
            if self.state != 'posted':
                raise UserError(_("Bill must be posted to accept on rs.ge (current state: %s).") % self.state)

        accept_result = service.buyer_accept_invoice(self._rs_inv_id_int, target_status=target_status)
        if not self._rs_send_succeeded(accept_result, 'acsept_invoice_statusResult'):
            self._rs_log("Failed to accept on rs.ge (target=%s): %s" % (target_status, accept_result), 'error')
            raise UserError(_("rs.ge refused the Accept call. See the RS Logs at the bottom of this tab and try again."))
        old = self.rs_einv_status
        expected = str(target_status)
        self.rs_einv_status = expected
        self._rs_log("Accepted on rs.ge (rs.ge acknowledged target %s -> %s)" % (old, expected))
        self.env.cr.commit()
        move = self._rs_relock_after_commit()
        if move:
            try:
                with self.env.cr.savepoint():
                    result = service.get_invoice(move._rs_inv_id_int)
                    new_status = str(getattr(result, 'status', ''))
                    if (new_status and new_status != expected and move.rs_einv_status == expected):
                        move.rs_einv_status = new_status
                        move._rs_log("Accept verification: rs.ge actually reports status %s (expected %s). Verify on rs.ge." % (new_status, expected),
                            'warning')
            except Exception as e:
                _logger.warning("Accept verification read failed on move %s (rs_id=%s): %s", self.id, self.rs_einv_id, e)
                move._rs_log("Accept acknowledged but verification read failed: %s. Click Check Status to confirm rs.ge state." % e, 'warning')
        else:
            _logger.info("Accept verification skipped for move %s: row busy or removed.", self.id)
        # Must run even if the verification lock was contended: it mirrors the rs.ge cancellation in the GL.
        target = move or self.exists()
        if target.rs_einv_status == '7' and target.state in ('draft', 'posted'):
            target._rs_auto_cancel_after_rs_cancellation()
        if target.rs_einv_status == '8' and target.rs_einv_replaces_id.state == 'posted':
            target.rs_einv_replaces_id._rs_neutralize_after_correction_accepted()

    def _rs_check_cancel_reissue_blockers(self):
        self.ensure_one()
        blockers = []
        if self.state != 'posted':
            blockers.append(_("Original bill %(name)s is in state '%(state)s' (only 'posted' bills can be auto-cancelled and reissued).",
                name=self.display_name or self.name or '—', state=self.state))
            return blockers
        if self.move_type != 'in_invoice':
            blockers.append(_("Only vendor bills (in_invoice) support buyer-side cancel-and-reissue; this document is '%s'.", self.move_type))
        if self.currency_id != self.company_currency_id:
            blockers.append(_("Bill %(name)s is in %(bill_ccy)s, but rs.ge correction amounts are in %(company_ccy)s. Create the vendor credit note "
                "manually and reconcile the FX difference with your accountant.", name=self.display_name or self.name or '—',
                bill_ccy=self.currency_id.name, company_ccy=self.company_currency_id.name))
        payment_state = getattr(self, 'payment_state', False) or 'not_paid'
        if payment_state not in ('not_paid', 'partial'):
            blockers.append(_("Original bill %(name)s has payment state '%(state)s' — unreconcile any payments before cancel-and-reissue.",
                name=self.display_name or self.name or '—', state=payment_state))
        if payment_state == 'partial':
            blockers.append(_("Original bill %(name)s is partially paid — unreconcile the payments before cancel-and-reissue.",
                name=self.display_name or self.name or '—'))
        if self.reversal_move_ids:
            cn_names = ", ".join(cn.display_name or cn.name or str(cn.id) for cn in self.reversal_move_ids[:3])
            blockers.append(_("Original bill %(name)s already has credit note(s) linked (%(cns)s). Resolve them before cancel-and-reissue.",
                name=self.display_name or self.name or '—', cns=cn_names))
        lock_check = self.company_id._get_user_fiscal_lock_date(self.journal_id) \
            if hasattr(self.company_id, '_get_user_fiscal_lock_date') else False
        if lock_check and self.invoice_date and self.invoice_date <= lock_check:
            blockers.append(_("Original bill %(name)s sits on or before the accounting lock date (%(lock)s). Cancel-and-reissue would alter a closed "
                "period — refuse.", name=self.display_name or self.name or '—', lock=lock_check))
        if self.rs_einv_replaced_by_id:
            blockers.append(_("Original bill %(name)s already points to a replacement (%(replacement)s). Resolve the existing chain before starting "
                "another one.", name=self.display_name or self.name or '—', replacement=(self.rs_einv_replaced_by_id.display_name or '—')))
        return blockers

    def _rs_execute_cancel_and_reissue(self, correction_rs_id):
        """The original stays posted until the buyer accepts the correction (8); a rejection leaves it live."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Cancel and Reissue'))
        service, verify, correction_id_int, verify_status = self._rs_reissue_verify_correction(correction_rs_id)

        original_state = self.state
        original_name = self.display_name or self.name or '—'
        original_amount = self.amount_total
        v_k_type = str(getattr(verify, 'k_type', '') or '').strip()
        new_draft = self._rs_reissue_create_draft(service, verify, correction_id_int, verify_status, v_k_type, correction_rs_id)
        self._rs_reissue_link_original(new_draft, verify_status)
        self._rs_reissue_post_chatter(new_draft, correction_rs_id, original_name, original_state, original_amount)
        self._rs_reissue_log_and_remind(new_draft, correction_rs_id, verify_status, v_k_type, original_name)
        return new_draft

    def _rs_reissue_verify_correction(self, correction_rs_id):
        if not correction_rs_id:
            raise UserError(_("No rs.ge correction ID was supplied. Re-open the inbox and try again."))
        if not self.rs_einv_id:
            raise UserError(_("Original bill %s has no linked rs.ge invoice — there is nothing to replace.", self.display_name or self.name or '—'))
        try:
            correction_id_int = int(correction_rs_id)
        except (TypeError, ValueError):
            raise UserError(_("rs.ge correction ID '%s' is not numeric — refuse to proceed.", correction_rs_id))

        blockers = self._rs_check_cancel_reissue_blockers()
        if blockers:
            raise UserError(_("Cannot cancel and reissue %(name)s:\n\n%(reasons)s", name=self.display_name or self.name or '—',
                reasons="\n".join("• %s" % r for r in blockers)))
        service = self._rs_get_service(check_auth=True)
        try:
            verify = service.get_invoice(correction_id_int)
        except Exception as e:
            raise UserError(_("Could not reach rs.ge to verify the correction (rs.ge ID: %s).\n\nDetails: %s", correction_rs_id, e))
        verify_status = str(getattr(verify, 'status', '') or '')
        if not verify_status or verify_status == '-1':
            raise UserError(_("rs.ge has no usable record for correction %s (status: '%s'). The supplier may have deleted it.", correction_rs_id,
                _rs_status_label(verify_status)))
        if verify_status not in ('5', '8'):
            raise UserError(_("rs.ge correction %(rs_id)s is at status '%(status)s' — only 'Correction Sent' or 'Correction Confirmed' can be "
                "auto-imported. Ask the supplier to send the correction on rs.ge, or refresh and try again.", rs_id=correction_rs_id,
                status=_rs_status_label(verify_status)))
        verify_k_id = getattr(verify, 'k_id', None)
        try:
            verify_k_id_int = int(verify_k_id or 0)
        except (TypeError, ValueError):
            verify_k_id_int = 0
        try:
            self_rs_id_int = int(self.rs_einv_id or 0)
        except (TypeError, ValueError):
            self_rs_id_int = 0
        if not self_rs_id_int or verify_k_id_int != self_rs_id_int:
            raise UserError(_("rs.ge correction %(rs_id)s does not point at this bill's rs.ge ID (%(parent_rs)s). Refuse to replace the wrong "
                "original.", rs_id=correction_rs_id, parent_rs=self.rs_einv_id))
        self._rs_pull_verify_parties(service, verify, rs_id=correction_rs_id)
        return service, verify, correction_id_int, verify_status

    def _rs_reissue_create_draft(self, service, verify, correction_id_int, verify_status, v_k_type, correction_rs_id):
        op_dt = getattr(verify, 'operation_dt', None)
        new_invoice_date = (op_dt.date() if op_dt and hasattr(op_dt, 'date') else fields.Date.today())
        copy_vals = {
            'invoice_date': new_invoice_date,
            'invoice_origin': self.invoice_origin,
            'rs_einv_replaces_id': self.id,
            'rs_einv_replacement_mode': 'fresh',
            'rs_einv_is_spec': self.rs_einv_is_spec,
        }
        if self.journal_id.type != 'purchase':
            purchase_journal = self.env['account.journal'].search([('type', '=', 'purchase'), ('company_id', '=', self.company_id.id)],
                order='sequence, id', limit=1)
            if not purchase_journal:
                raise UserError(_("No purchase journal available for company %s — cannot create the new draft bill.", self.company_id.display_name))
            copy_vals['journal_id'] = purchase_journal.id
        new_draft = self.with_company(self.company_id).with_context(include_business_fields=True).copy(copy_vals)
        draft_vals = {
            'rs_einv_id': str(correction_id_int),
            'rs_einv_status': verify_status,
            'rs_einv_series': getattr(verify, 'f_series', '') or '',
            'rs_einv_number': _rs_clean_number(getattr(verify, 'f_number', '')),
        }
        if v_k_type in ('1', '2', '3', '4'):
            draft_vals.update(rs_einv_k_type=v_k_type)
        new_draft.write(draft_vals)
        new_draft._rs_refresh_pulled_lines(service, raise_on_failure=True)
        if new_draft.rs_einv_pulled_line_ids:
            new_draft._rs_merge_pulled_to_bill_lines()
        else:
            new_draft._rs_product_lines().unlink()
            new_draft._rs_log("rs.ge correction %s has no lines, so this replacement bill has none either." % correction_rs_id, 'warning')
        return new_draft

    def _rs_reissue_link_original(self, new_draft, verify_status):
        self.write({'rs_einv_replaced_by_id': new_draft.id})
        if verify_status == '8':
            self._rs_neutralize_after_correction_accepted()

    def _rs_reissue_post_chatter(self, new_draft, correction_rs_id, original_name, original_state, original_amount):
        try:
            parent_link = Markup('<a href="#" data-oe-model="account.move" data-oe-id="%d">%s</a>') % (self.id, original_name)
            new_link = Markup('<a href="#" '
                'data-oe-model="account.move" data-oe-id="%d">%s</a>') % (new_draft.id, new_draft.display_name or new_draft.name or '—')
            if new_draft.rs_einv_status == '8':
                created_text = _("Replacement draft created from rs.ge correction %(rs_id)s: %(new)s. The correction is already accepted on rs.ge.")
            else:
                created_text = _("Replacement draft created from rs.ge correction %(rs_id)s: %(new)s. This bill is cancelled once the correction is "
                    "accepted on rs.ge.")
            self.message_post(body=Markup(created_text) % {'rs_id': escape(correction_rs_id), 'new': new_link})
            new_draft.message_post(body=Markup(_(
                "Created by rs.ge cancel-and-reissue. Replaces "
                "%(parent)s (was in state '%(state)s', amount "
                "%(amount).2f). rs.ge correction ID %(rs_id)s."
            )) % {
                'parent': parent_link,
                'state': escape(original_state),
                'amount': original_amount,
                'rs_id': escape(correction_rs_id),
            })
        except Exception:
            _logger.exception("Cancel-and-reissue: chatter cross-reference failed (parent=%s, new=%s)", self.id, new_draft.id)

    def _rs_reissue_log_and_remind(self, new_draft, correction_rs_id, verify_status, v_k_type, original_name):
        new_draft._rs_log("Created via cancel-and-reissue from %s "
            "(rs.ge correction ID %s, status %s, k_type %s)." % (original_name, correction_rs_id, _rs_status_label(verify_status), v_k_type or '—'))
        if verify_status == '5':
            pending_msg = _("Supplier correction %(rs_id)s is still PENDING your acceptance on rs.ge (status 'Correction Sent'). Post this "
                "replacement bill and click 'Accept on rs.ge' to confirm it — rs.ge will move it 5 -> 8. Until then rs.ge and Odoo disagree on this "
                "correction.", rs_id=correction_rs_id)
            new_draft._rs_log(pending_msg, 'warning')
            try:
                new_draft.activity_schedule('mail.mail_activity_data_todo', summary=_("Accept supplier correction on rs.ge"), note=pending_msg,
                    user_id=self.env.user.id)
            except Exception:
                _logger.exception("Could not schedule correction-accept activity on move %s", new_draft.id)
        elif verify_status == '8':
            if self.rs_einv_reversal_pending_at:
                msg = _("Supplier correction %(rs_id)s is already confirmed on rs.ge. Check this corrected bill and post it; %(bill)s could not be "
                    "cancelled automatically, see its To-Do.", rs_id=correction_rs_id, bill=original_name)
            else:
                msg = _("Supplier correction %(rs_id)s is already confirmed on rs.ge and %(bill)s is cancelled or reversed. Check this corrected "
                    "bill and post it.", rs_id=correction_rs_id, bill=original_name)
            new_draft._rs_notify(msg, 'warning', activity_xmlid='mail.mail_activity_data_todo', activity_summary=_("Post the corrected bill"))

    def action_rs_import_supplier_correction(self):
        """This bill is cancelled, not credited, once the supplier correction is accepted on rs.ge."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Import Supplier Correction'))
        if not self.rs_einv_is_buyer_side:
            raise UserError(_("Import Supplier Correction only applies to vendor bills."))
        if not self.rs_einv_supplier_k_id:
            self._rs_safe_refresh_status()
            if not self.rs_einv_supplier_k_id:
                raise UserError(_("No pending supplier correction was found for this bill. Click 'Check Status' first — if the supplier really "
                    "filed a correction on rs.ge, it will be detected."))

        new_k_id = self.rs_einv_supplier_k_id
        existing = self._rs_find_other_move_by_rs_id(new_k_id)
        if existing:
            if existing.reversed_entry_id == self:
                self.rs_einv_supplier_k_id = False
            raise UserError(_("Supplier correction %(rs_id)s is already linked to "
                "%(name)s. Open that replacement bill instead of importing it again.", rs_id=new_k_id,
                name=existing.display_name or existing.name or '—'))
        new_draft = self._rs_execute_cancel_and_reissue(new_k_id)
        self.rs_einv_supplier_k_id = False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Replacement Bill'),
            'res_model': 'account.move',
            'res_id': new_draft.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_rs_buyer_reject(self):
        self.ensure_one()
        if not self.rs_einv_is_buyer_side:
            raise UserError(_("Reject on rs.ge only applies to vendor bills and vendor credit notes."))
        if not self.rs_einv_id:
            raise UserError(_("No rs.ge ID linked yet — click 'Pull from rs.ge' first."))

        self._rs_safe_refresh_status()

        if self.rs_einv_status not in RS_PENDING_BUYER:
            raise UserError(_("You can only reject records that are waiting for your confirmation ('Sent (Pending)' or 'Correction Sent'). Current "
                "rs.ge status: '%s'.", _rs_status_label(self.rs_einv_status)))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Vendor Invoice"),
            'res_model': 'rs.einvoice.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def _rs_do_buyer_reject(self, reason):
        self.ensure_one()
        clean_reason = (reason or '').strip()
        if not clean_reason:
            raise UserError(_("rs.ge requires a rejection reason — fill in the Reason field."))

        self._rs_acquire_row_lock(_('Reject on rs.ge'))
        self._rs_safe_refresh_status()
        if self.rs_einv_status not in RS_PENDING_BUYER:
            raise UserError(_("This document is no longer rejectable — current rs.ge status: '%s'. Refresh and re-check before rejecting.",
                _rs_status_label(self.rs_einv_status)))
        paid_states = ('paid', 'partial', 'in_payment')
        if (hasattr(self, 'payment_state') and self.payment_state in paid_states):
            raise UserError(_(
                "This bill is already %(state)s and has reconciled payment(s). "
                "Reject on rs.ge would invite a reversal that drives AP "
                "negative.\n\n"
                "What to do:\n"
                "1. Unreconcile the payment(s) (Accounting > Reconciliation).\n"
                "2. Reset the bill to draft if needed.\n"
                "3. Then come back and reject."
            ) % {'state': self.payment_state})

        service = self._rs_get_service(check_auth=True)
        old_status = self.rs_einv_status
        reject_result = service.buyer_reject_invoice(self._rs_inv_id_int, clean_reason)
        success = bool(getattr(reject_result, 'ref_invoice_statusResult', reject_result))
        if not success:
            self._rs_log("Failed to reject on rs.ge: %s" % reject_result, 'error')
            raise UserError(_("rs.ge refused the rejection. See the RS Logs at the bottom of this tab and try again."))

        fallback_status = {'1': '0', '5': '4'}.get(old_status)
        if fallback_status:
            self.rs_einv_status = fallback_status
        self.rs_einv_rejection_reason = clean_reason
        if self.rs_einv_is_buyer_side:
            self.rs_einv_rejection_note = _("You rejected this document on rs.ge. Reason sent to supplier: %s. Odoo will cancel the local document "
                "once it confirms rs.ge moved the document off pending.") % clean_reason
        self._rs_log("Rejected on rs.ge (status: %s "
            "-> %s). Reason sent to supplier: %s" % (old_status, fallback_status or 'pending verification', clean_reason))
        self._rs_post(_("Rejected on rs.ge. Reason sent to supplier: %s", clean_reason))
        self.env.cr.commit()

        move = self._rs_relock_after_commit()
        if not move:
            _logger.info("Reject verification skipped for move %s: row busy or removed. Cancel manually once rs.ge confirms the rejection.", self.id)
            return
        try:
            result = service.get_invoice(move._rs_inv_id_int)
        except Exception as e:
            _logger.warning("Reject succeeded but status verification failed for move %s (rs_id=%s): %s", self.id, self.rs_einv_id, e)
            move._rs_log("Reject succeeded on rs.ge but status verification failed: %s. The bill was NOT auto-cancelled — click Check Status, then "
                "cancel it manually so Odoo matches rs.ge." % e, 'warning')
            return
        new_status = str(getattr(result, 'status', ''))
        if not new_status:
            move._rs_log("Reject call succeeded but the new rs.ge status could not be verified. The bill was NOT auto-cancelled — click Check "
                "Status and cancel manually if rs.ge shows it rejected. Reason sent: %s" % clean_reason, 'warning')
            return
        if new_status in RS_PENDING_BUYER:
            move.rs_einv_status = new_status
            move._rs_log("Reject verification shows rs.ge still pending (status %s); the bill was NOT cancelled. Re-check on rs.ge and retry the "
                "rejection." % new_status, 'warning')
            return
        current = move.rs_einv_status
        move.rs_einv_status = new_status
        move.rs_einv_rejection_reason = clean_reason
        move._rs_log("Rejected on rs.ge (status: %s -> %s). Reason sent to supplier: %s" % (current, new_status, clean_reason))
        if move.rs_einv_is_buyer_side and move.state in ('draft', 'posted'):
            move.rs_einv_rejection_note = _("You rejected this document on rs.ge. Reason sent to supplier: %s. The local document has been cancelled "
                "in Odoo.") % clean_reason
            move._rs_auto_cancel_after_rs_cancellation()

    def action_rs_resolve_orphan(self):
        """Orphan = rs.ge draft created by a timed-out request; correction orphans must be dismissed, not linked."""
        self.ensure_one()
        if not self.rs_einv_pending_action:
            raise UserError(_("There is no pending rs.ge action on this document — nothing to resolve."))
        if self.rs_einv_id:
            self._rs_clear_pending()
            self._rs_log("Cleared pending RS action marker (%s) — document already has rs.ge ID %s." % (self.rs_einv_pending_action, self.rs_einv_id))
            return
        return {
            'type': 'ir.actions.act_window',
            'name': _('Resolve Orphan rs.ge Record'),
            'res_model': 'rs.einvoice.orphan.resolve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def _rs_do_resolve_orphan(self, candidate_id):
        self.ensure_one()
        if not candidate_id:
            raise UserError(_("Enter the rs.ge ID you want to verify."))
        try:
            candidate_id_int = int(candidate_id)
        except (TypeError, ValueError):
            raise UserError(_("'%s' is not a valid rs.ge ID — only digits are allowed.", candidate_id))
        if candidate_id_int <= 0:
            raise UserError(_("rs.ge ID must be a positive number."))
        existing = self._rs_find_other_move_by_rs_id(candidate_id_int, use_sudo=True)
        if existing:
            raise UserError(_("rs.ge ID %(rs_id)s is already linked to %(name)s. Each rs.ge record may only be attached to one Odoo move — open the "
                "existing document instead of relinking it here.", rs_id=candidate_id_int, name=existing.display_name or existing.name))

        service = self._rs_get_service(check_auth=True)
        try:
            result = service.get_invoice(candidate_id_int)
        except Exception as e:
            raise UserError(_("Could not reach rs.ge to check this ID.\n\nDetails: %s", e))
        status = str(getattr(result, 'status', ''))
        if not status or status == '-1':
            raise UserError(_("rs.ge has no usable record for ID %s (status: '%s').", candidate_id_int, _rs_status_label(status)))
        seller_un_id = int(getattr(result, 'seller_un_id', 0) or 0)
        buyer_un_id = int(getattr(result, 'buyer_un_id', 0) or 0)
        if self.move_type in ('in_invoice', 'in_refund'):
            raise UserError(_("Resolve Orphan is only available for customer-side documents (sales invoices and customer credit notes). Vendor-side "
                "rs.ge records must be linked through 'Pull from rs.ge' — paste the supplier's ID and click Pull."))
        if not seller_un_id or not buyer_un_id:
            raise UserError(_("rs.ge returned no seller or buyer identifier for ID %s (seller=%s, buyer=%s). Cannot verify ownership — refuse to "
                "link.", candidate_id_int, seller_un_id or '—', buyer_un_id or '—'))
        try:
            our_un_id = service._rs_company_un_id()
        except Exception as e:
            raise UserError(_("Could not verify your company identity against rs.ge before linking this orphan.\n\nDetails: %s", e))
        if not our_un_id:
            raise UserError(_("rs.ge did not return your company's identifier, so Odoo cannot safely verify this orphan. Try again later."))
        if not self.partner_id.vat:
            raise UserError(_("Cannot verify this orphan because the customer has no TIN on the partner record. Fill the customer's VAT/TIN first, "
                "then try Resolve Orphan again."))
        try:
            partner_un_id = service._rs_partner_un_id(self.partner_id)
        except Exception as e:
            raise UserError(_("Could not verify the customer's TIN against rs.ge before linking this orphan (TIN: %(tin)s).\n\nDetails: %(err)s",
                tin=self.partner_id.vat, err=e))
        if not partner_un_id:
            raise UserError(_("rs.ge did not return an identifier for customer TIN %s. Odoo cannot safely link this orphan.", self.partner_id.vat))
        if int(our_un_id) != seller_un_id:
            raise UserError(_("rs.ge record %s belongs to a different seller, not your company. This is not the orphan for this invoice.",
                candidate_id_int))
        if int(partner_un_id) != buyer_un_id:
            raise UserError(_("rs.ge record %s is addressed to a different buyer than the partner on this invoice. This is the wrong orphan — "
                "double-check the ID on rs.ge.", candidate_id_int))

        self.write({
            'rs_einv_id': str(candidate_id_int),
            'rs_einv_status': status,
            'rs_einv_series': getattr(result, 'f_series', '') or '',
            'rs_einv_number': _rs_clean_number(getattr(result, 'f_number', '')),
        })
        self._rs_clear_pending()
        self._rs_log("Resolved orphan rs.ge record %s (status %s) — linked to this document after manual verification." % (candidate_id_int, status))

    def action_rs_clear_pending(self):
        """Clear the pending marker without linking; use only after confirming no rs.ge record exists."""
        self.ensure_one()
        if not self.rs_einv_pending_action:
            return
        self._rs_acquire_row_lock(_('Dismiss Pending'))
        pending_at = self.rs_einv_pending_action_at
        min_age = timedelta(minutes=_RS_PENDING_DISMISS_MIN_AGE_MINUTES)
        if pending_at and pending_at > fields.Datetime.now() - min_age:
            raise UserError(_(
                "This pending rs.ge action started less than %(mins)d minutes "
                "ago (%(since)s) — the original request may still be running "
                "on rs.ge. Dismissing it now could let a retry create a "
                "duplicate document.\n\n"
                "Wait until the marker is older, click 'Check Status' to see "
                "whether an ID arrived, or use 'Resolve Orphan' to link the "
                "rs.ge draft instead.",
                mins=_RS_PENDING_DISMISS_MIN_AGE_MINUTES,
                since=pending_at,
            ))
        self._rs_log("Pending RS action marker '%s' cleared by operator "
            "without linking — operator confirmed no rs.ge record exists." % (self.rs_einv_pending_action,), 'warning')
        self._rs_clear_pending()

    def action_rs_view_reversals(self):
        self.ensure_one()
        moves = self.reversal_move_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Reversal Credit Notes'),
            'res_model': 'account.move',
            'context': dict(self.env.context, create=False),
        }
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'res_id': moves.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)]})
        return action

    def action_rs_view_replacement(self):
        self.ensure_one()
        if not self.rs_einv_replaced_by_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Replacement Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.rs_einv_replaced_by_id.id,
            'context': dict(self.env.context, create=False),
        }

    def action_rs_view_replaces(self):
        self.ensure_one()
        if not self.rs_einv_replaces_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Original Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.rs_einv_replaces_id.id,
            'context': dict(self.env.context, create=False),
        }

    def action_rs_clear_cancelled_replacement_link(self):
        self.ensure_one()
        replacement = self.rs_einv_replaced_by_id
        if not replacement or replacement.state != 'cancel':
            raise UserError(_("There is no cancelled replacement invoice linked to this document."))
        if replacement.rs_einv_id and replacement.rs_einv_status != '-1':
            raise UserError(_("Cannot clear the replacement link yet. Replacement %(name)s still has rs.ge ID %(rs_id)s at status %(status)s. Open "
                "the replacement, delete it on rs.ge if allowed, or run Check Status before clearing the link.",
                name=replacement.display_name or replacement.name or '—', rs_id=replacement.rs_einv_id,
                status=_rs_status_label(replacement.rs_einv_status)))
        replacement_name = replacement.display_name or replacement.name or '—'
        self.write({'rs_einv_replaced_by_id': False})
        replacement.write({'rs_einv_replaces_id': False, 'rs_einv_replacement_mode': False})
        msg = _("Cancelled replacement link cleared. Former replacement: %s.", replacement_name)
        self._rs_log(msg, 'warning')
        replacement._rs_log("Replacement link cleared from original %s." % (self.display_name or self.name or '—',), 'warning')
        try:
            self.message_post(body=msg)
            replacement.message_post(body=_("Replacement link cleared from original %s.", self.display_name or self.name or '—'))
        except Exception:
            pass
        return {'type': 'ir.actions.client', 'tag': 'reload'}
