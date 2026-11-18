import logging
from collections import defaultdict

from odoo import models, Command, _
from odoo.exceptions import UserError

from .account_move import _rs_clean_number, _rs_status_label, rs_to_float, RS_ACCEPTED, RS_CONFIRMED, RS_DRAFT_OR_NEW_CORRECTION, RS_PENDING_BUYER

_logger = logging.getLogger(__name__)

RS_STANDARD_TAX_CATEGORY = 'S'
RS_VAT_CLASS_BY_TAX_CATEGORY = {RS_STANDARD_TAX_CATEGORY: 'taxable', 'Z': 'zero', 'G': 'zero', 'K': 'zero', 'E': 'untaxed', 'O': 'untaxed'}


def _rs_tax_vat_classes(taxes):
    return {
        RS_VAT_CLASS_BY_TAX_CATEGORY[tax.ubl_cii_tax_category_code]
        for tax in taxes if tax.ubl_cii_tax_category_code in RS_VAT_CLASS_BY_TAX_CATEGORY
    }


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_rs_refresh_status(self):
        """Skips a never-pulled vendor bill (only Pull links it)."""
        self.ensure_one()
        if not self.rs_einv_id or self._rs_awaiting_pull():
            return
        excluded_ids = set(self.env.context.get('rs_refresh_excluded_ids') or ())
        service = self._rs_get_service()
        result = service.get_invoice(self._rs_inv_id_int)
        status = str(getattr(result, 'status', ''))
        self._rs_refresh_header(result)
        previous_status = self.rs_einv_status
        self._rs_refresh_rejection(result, status, previous_status)
        self._rs_refresh_apply_status(status, previous_status)
        self._rs_refresh_supplier_correction(service)
        refreshed_child_ids = self._rs_refresh_replacements(service, excluded_ids)
        if self.rs_einv_is_buyer_side:
            self._rs_refresh_pulled_lines(service)
        self._rs_refresh_parent(excluded_ids, refreshed_child_ids)

    def _rs_refresh_header(self, result):
        seq_num_s = _rs_clean_number(getattr(result, 'seq_num_s', '')) or False
        seq_num_b = _rs_clean_number(getattr(result, 'seq_num_b', '')) or False
        self.write({
            'rs_einv_series': getattr(result, 'f_series', '') or '',
            'rs_einv_number': _rs_clean_number(getattr(result, 'f_number', '')),
            'rs_einv_seq_num_s': seq_num_s,
            'rs_einv_seq_num_b': seq_num_b,
            'rs_einv_overhead_no': (seq_num_b if self.rs_einv_is_buyer_side else seq_num_s) or False,
        })

    def _rs_refresh_rejection(self, result, status, previous_status):
        was_ref = bool(getattr(result, 'was_ref', False))
        going_back = (
            (previous_status == '2' and status == '1')
            or (previous_status == '5' and status == '4')
            or (previous_status == '1' and status == '0')
        )
        currently_pending = status in RS_PENDING_BUYER
        currently_confirmed = status in RS_CONFIRMED
        post_send_drop_to_draft = (status == '0' and bool(self.rs_einv_sent_at) and previous_status in RS_PENDING_BUYER)
        resent_to_buyer = (self.rs_einv_is_buyer_side and currently_pending and previous_status in RS_DRAFT_OR_NEW_CORRECTION)
        active_rejection = (going_back or (was_ref and currently_pending) or post_send_drop_to_draft)
        rejection_signature = ("%s:%s" % (status or '', '1' if was_ref else '0') if active_rejection else False)
        if active_rejection and not self.rs_einv_is_buyer_side:
            if going_back:
                note = _("Likely buyer rejection detected (status %(prev)s → %(curr)s). Open the document on rs.ge to read the rejection reason "
                    "supplied by the buyer.", prev=_rs_status_label(previous_status), curr=_rs_status_label(status))
            else:
                note = _("rs.ge reports this document was rejected (current status: '%s'). Open the document on rs.ge to read the rejection reason — "
                    "then use 'Update on RS' to fix and re-send.", _rs_status_label(status))
            new_signature = rejection_signature != (self.rs_einv_rejection_status or False)
            if new_signature:
                self.rs_einv_rejection_note = note
                self.rs_einv_rejection_status = rejection_signature
                self._rs_notify(note, 'warning', post_chatter=True)
                if (status == '4' and self.rs_einv_replacement_mode == 'correction' and self.rs_einv_replaces_id and self.state == 'posted'):
                    self._rs_reset_correction_to_draft_after_rejection()
        elif (currently_confirmed or resent_to_buyer) and (self.rs_einv_rejection_note or self.rs_einv_rejection_status):
            self.rs_einv_rejection_note = False
            self.rs_einv_rejection_status = False

    def _rs_refresh_apply_status(self, status, previous_status):
        """Status 7 and 8 actions have no done-flag: they run on every refresh while their state checks hold."""
        if status and status != self.rs_einv_status:
            old = self.rs_einv_status
            self.rs_einv_status = status
            self._rs_log("Status updated: %s -> %s" % (old, status))
            if (previous_status == '6' and status in RS_CONFIRMED and not self.rs_einv_is_buyer_side):
                if self.rs_einv_cancel_pending_at:
                    self.rs_einv_cancel_pending_at = False
                msg = _("Buyer rejected the cancellation on rs.ge (status %(prev)s -> %(curr)s). The invoice is live again — Odoo accounting was not "
                    "changed. Use Cancel on RS to retry, or Cancel "
                    "& Reissue if the document needs to be replaced.") % {'prev': _rs_status_label(previous_status), 'curr': _rs_status_label(status)}
                self._rs_notify(msg, 'warning', post_chatter=True)
                self._rs_release_stranded_replacement()
            if status == '6' and previous_status in RS_ACCEPTED and not self.rs_einv_is_buyer_side and not self.rs_einv_cancel_pending_at:
                self._rs_schedule_cancel_pending_activity(self.rs_einv_id)
        if (status == '8'
                and (self.rs_einv_replacement_mode == 'correction' or self.rs_einv_is_buyer_side)
                and self.state != 'cancel'
                and self._rs_post_accepted_correction()
                and self.rs_einv_replaces_id.state == 'posted'):
            self.rs_einv_replaces_id._rs_neutralize_after_correction_accepted()
        if (status == '7' and self.move_type in ('out_invoice', 'in_invoice') and self.state == 'posted' and self.payment_state != 'reversed'):
            if self.rs_einv_cancel_pending_at:
                self.rs_einv_cancel_pending_at = False
            self._rs_auto_cancel_after_rs_cancellation()

    def _rs_refresh_supplier_correction(self, service):
        """Buyer side: rs_einv_supplier_k_id holds the supplier's correction ID until linked or none on rs.ge."""
        if not (self.rs_einv_is_buyer_side and not self.rs_einv_replaced_by_id and self.state != 'cancel'):
            return
        try:
            k_id_int = service.get_makoreqtirebeli(self._rs_inv_id_int)
        except Exception as e:
            _logger.warning("get_makoreqtirebeli failed for inv_id=%s: %s", self.rs_einv_id, e)
            k_id_int = 0
        if k_id_int and k_id_int > 0:
            k_id_str = str(k_id_int)
            already_known = k_id_str == (self.rs_einv_id or '')
            if isinstance(self.id, int):
                already_known = already_known or bool(self.env['account.move'].search([
                    ('rs_einv_id', '=', k_id_str),
                    ('rs_einv_replaces_id', '=', self.id),
                    ('company_id', '=', self.company_id.id),
                ], limit=1))
            if not already_known:
                if self.rs_einv_supplier_k_id != k_id_str:
                    self.rs_einv_supplier_k_id = k_id_str
                    msg = _("Supplier has issued a correction on rs.ge (correction ID %s). Click 'Import Supplier Correction' on the RS E-Invoice "
                        "tab to pull it into Odoo as a vendor credit note.", k_id_str)
                    self._rs_notify(msg, 'warning', post_chatter=True)
            else:
                if self.rs_einv_supplier_k_id == k_id_str:
                    self.rs_einv_supplier_k_id = False
        elif self.rs_einv_supplier_k_id:
            self.rs_einv_supplier_k_id = False

    def _rs_refresh_replacements(self, service, excluded_ids):
        """Returns refreshed ids for the parent to skip; a status-8 replacement retries its cancel each refresh."""
        refreshed_child_ids = set()
        if isinstance(self.id, int):
            inv_domain = [
                ('rs_einv_replaces_id', '=', self.id),
                ('rs_einv_replacement_mode', 'in', ['correction', 'fresh']),
                ('rs_einv_id', '!=', False),
            ]
            if excluded_ids:
                inv_domain.append(('id', 'not in', list(excluded_ids)))
            invoice_corrections = self.env['account.move'].search(inv_domain)
            for inv_move in invoice_corrections:
                try:
                    inv_result = service.get_invoice(int(inv_move.rs_einv_id))
                except Exception as e:
                    _logger.warning("Could not refresh invoice-driven correction %s: %s", inv_move.rs_einv_id, e)
                    continue
                inv_status, inv_series, inv_number = self._rs_extract_status_triplet(inv_result)
                if inv_status and inv_status != inv_move.rs_einv_status:
                    old = inv_move.rs_einv_status
                    inv_move._rs_refresh_rejection(inv_result, inv_status, old)
                    inv_move.rs_einv_status = inv_status
                    inv_move._rs_log("Status pulled by parent refresh: %s -> %s" % (old, inv_status))
                if inv_series:
                    inv_move.rs_einv_series = inv_series
                if inv_number:
                    inv_move.rs_einv_number = inv_number
                if (inv_move.rs_einv_status == '8' and inv_move.state != 'cancel'
                        and (inv_move.rs_einv_replacement_mode == 'correction' or inv_move.rs_einv_is_buyer_side)
                        and inv_move._rs_post_accepted_correction()):
                    self._rs_neutralize_after_correction_accepted()
                refreshed_child_ids.add(inv_move.id)
        return refreshed_child_ids

    def _rs_refresh_parent(self, excluded_ids, refreshed_child_ids):
        """Passes the ids refreshed so far in the context, so the refresh never loops back to them."""
        parent = self._rs_chain_parent(modes=('correction', 'fresh'))
        if (parent and parent.rs_einv_id and not parent.rs_einv_skip and parent.id not in excluded_ids and parent.id != self.id):
            new_excluded = tuple(excluded_ids | {self.id} | refreshed_child_ids)
            try:
                parent.with_context(rs_refresh_excluded_ids=new_excluded).action_rs_refresh_status()
            except Exception as e:
                _logger.warning("Upward refresh of parent %s after correction %s refresh failed: %s", parent.display_name, self.display_name, e)
                self._rs_log("Refreshed self but could not refresh parent %s: %s. Click Check Status on the parent directly if its status looks "
                    "stale." % (parent.display_name, e), 'warning')

    def _rs_sync_lines(self, service, target_id=None):
        """Not transactional: a failure can leave rs.ge with a mix of old and new lines."""
        if target_id is None:
            target_id = self._rs_inv_id_int

        try:
            existing_rows = service.get_invoice_desc(target_id) or []
        except Exception as e:
            self._rs_log("Could not fetch existing RS lines before sync (id=%s): %s" % (target_id, e), 'error')
            raise UserError(_("Could not read the current line state from rs.ge (rs.ge ID: %s). The network or rs.ge may be down — nothing was "
                "changed. Try again in a moment.", target_id))
        existing_ids = []
        for idx, row in enumerate(existing_rows):
            rid = row.get('id') if isinstance(row, dict) else getattr(row, 'id', None)
            if rid in (None, '', 0, '0'):
                raise UserError(_("rs.ge returned a line without an ID for invoice %s. Sync was aborted to avoid writing to the wrong slot. Click "
                    "Check Status and try again. If the problem stays, contact support.", target_id))
            try:
                existing_ids.append(int(rid))
            except (TypeError, ValueError):
                raise UserError(_("rs.ge returned an unreadable line ID ('%s') for invoice %s. Sync was aborted to avoid writing to the wrong slot. "
                    "Contact support.", rid, target_id))

        payloads = self._rs_get_lines_payload()

        reused_ids = []
        failed_line = None
        committed_writes = 0
        for i, payload in enumerate(payloads):
            slot_id = existing_ids[i] if i < len(existing_ids) else 0
            if slot_id and i < len(existing_rows) and self._rs_line_matches_slot(payload, existing_rows[i]):
                reused_ids.append(slot_id)
                continue
            try:
                result = service.save_invoice_desc(inv_id=target_id, goods=payload['goods'], g_unit=payload['g_unit'], quantity=payload['qty'],
                    full_amount=payload['full_amount'], vat_amount=payload['vat_amount'], desc_id=slot_id)
            except Exception as e:
                self._rs_log("Exception syncing line '%s' (slot=%s): %s" % (payload['goods'], slot_id, e), 'error')
                failed_line = payload['goods']
                break
            success = getattr(result, 'save_invoice_descResult', False)
            desc_id = getattr(result, 'id', 0)
            if success and desc_id and desc_id > 0:
                reused_ids.append(int(desc_id))
                committed_writes += 1
            else:
                self._rs_log("Failed to sync line '%s' (slot=%s): %s" % (payload['goods'], slot_id, result), 'error')
                failed_line = payload['goods']
                break
        if failed_line is not None:
            if committed_writes > 0:
                self._rs_mark_lines_partial()
                self._rs_schedule_line_sync_activity(target_id, failed_line, committed_writes, len(payloads))
                raise UserError(_(
                    "Line sync failed at '%s' after %d slot(s) were "
                    "already updated on rs.ge.\n\n"
                    "rs.ge now holds a MIX of old and new lines for this "
                    "document. Fix the underlying issue and click Update "
                    "on RS again — the next sync will overwrite the "
                    "remaining stale slots from the current Odoo state.",
                    failed_line, committed_writes,
                ))
            raise UserError(_(
                "Could not sync line '%s' to rs.ge.\n\n"
                "No slot was updated before the failure — the previous "
                "lines on rs.ge are still intact. Fix the issue and try "
                "again.",
                failed_line,
            ))

        leftover_ids = [eid for eid in existing_ids if eid not in reused_ids]
        failed_deletes = []
        for eid in leftover_ids:
            try:
                deleted = service.delete_invoice_desc(eid, target_id)
            except Exception as e:
                _logger.warning("delete_invoice_desc(%s, %s) failed on move %s: %s", eid, target_id, self.id, e)
                deleted = False
            if not deleted:
                failed_deletes.append(eid)
        if failed_deletes:
            self._rs_mark_lines_partial()
            self._rs_schedule_line_sync_activity(target_id, _("old line removal"), len(payloads), len(payloads))
            raise UserError(_("The lines were saved on rs.ge, but %(count)d old line(s) could not be removed (rs.ge line ID: %(ids)s), so rs.ge "
                "still shows extra lines. Do not send to the buyer yet: click Update on RS again.", count=len(failed_deletes),
                ids=', '.join(str(eid) for eid in failed_deletes)))

        try:
            final_rows = service.get_invoice_desc(target_id) or []
        except Exception as e:
            _logger.warning("Post-sync line read failed for rs.ge invoice %s (move %s): %s", target_id, self.id, e)
            self._rs_mark_lines_partial()
            self._rs_schedule_line_sync_activity(target_id, _("line read-back"), len(payloads), len(payloads))
            raise UserError(_("The lines were saved on rs.ge, but Odoo could not read them back to check them (rs.ge ID: %s). Do not send to the "
                "buyer yet: click Update on RS again.", target_id))
        if len(final_rows) != len(payloads):
            self._rs_mark_lines_partial()
            self._rs_log("Post-sync line count mismatch: Odoo=%d, rs.ge=%d (id=%s)" % (len(payloads), len(final_rows), target_id), 'error')
            self._rs_schedule_line_sync_activity(target_id, _("line count verification"), len(payloads), len(payloads))
            raise UserError(_("Line sync finished but the counts do not match — Odoo has %d line(s) and rs.ge has %d. Likely a stale row was left on "
                "rs.ge. Click Update on RS again, and check the rs.ge document directly if the mismatch keeps happening.", len(payloads),
                len(final_rows)))
        if self.rs_einv_lines_sync_state == 'partial':
            self.rs_einv_lines_sync_state = 'in_sync'

    def _rs_get_lines_payload(self):
        self.ensure_one()
        return self._rs_lines_to_payload(self.invoice_line_ids)

    def _rs_lines_to_payload(self, lines):
        """Down-payment deductions are spread only over regular lines with the same VAT treatment, so rs.ge
        gets the books' taxed base and VAT."""
        product_lines = lines.filtered(lambda l: l.display_type == 'product')
        if not product_lines:
            product_lines = lines.filtered(lambda l: l.price_total != 0)
        owner = product_lines[:1].move_id if product_lines else self
        line_model = self.env['account.move.line']
        has_offset = (owner and 'is_downpayment' in line_model._fields and owner._rs_has_downpayment_offset_lines())
        if not has_offset:
            return [self._rs_line_to_payload(line) for line in product_lines]

        regular_lines = product_lines.filtered(lambda l: not l.is_downpayment)
        offset_lines = product_lines.filtered(lambda l: l.is_downpayment)
        if owner == self and owner._rs_uses_native_advance_attach():
            return [self._rs_line_to_payload(line) for line in regular_lines]

        def _gross_gel(l):
            return abs((l.move_id or self)._rs_amount_to_gel(l.price_total or 0))

        total_regular_gross = sum(_gross_gel(l) for l in regular_lines)
        total_offset_gross = sum(_gross_gel(l) for l in offset_lines)

        if total_regular_gross <= 0.01:
            return [self._rs_line_to_payload(line) for line in regular_lines]
        if total_offset_gross >= total_regular_gross - 0.01:
            raise UserError(_("The net total after the down-payment deduction is zero or negative — there is nothing to file on rs.ge. Review the "
                "down-payment allocation on this invoice."))

        payloads = []
        for line in regular_lines:
            payload = self._rs_line_to_payload(line)
            if payload['full_amount'] > 0:
                payloads.append(payload)
        offsets = defaultdict(lambda: [0.0, 0.0])
        for line in offset_lines:
            move = line.move_id or self
            vat_class, vat = move._rs_line_vat_class(line)
            offset = offsets[vat_class]
            offset[0] += _gross_gel(line)
            offset[1] += abs(move._rs_amount_to_gel(vat))
        treatment_labels = {'taxable': _("VAT-taxed"), 'zero': _("zero-rated"), 'untaxed': _("VAT-free")}
        dropped = set()
        for vat_class, (offset_gross, offset_vat) in offsets.items():
            members = [p for p in payloads if self._rs_vat_class(p['vat_amount']) == vat_class]
            class_gross = sum(p['full_amount'] for p in members)
            if offset_gross > class_gross + 0.01:
                raise UserError(_(
                    "The down-payment deduction on %(treatment)s lines "
                    "(%(offset).2f GEL) is larger than the delivered "
                    "%(treatment)s goods (%(goods).2f GEL). Net settlement "
                    "cannot show this on rs.ge.\n\n"
                    "Issue an advance correction, or switch this invoice's "
                    "Advance Settlement to the native attach/detach mode.",
                    treatment=treatment_labels[vat_class],
                    offset=offset_gross, goods=class_gross,
                ))
            class_vat = sum(p['vat_amount'] for p in members) if vat_class == 'taxable' else 0.0
            for p in members:
                adjusted = self._rs_round(p['full_amount'] - offset_gross * p['full_amount'] / class_gross, 2)
                if vat_class == 'taxable':
                    p['vat_amount'] = self._rs_round(p['vat_amount'] * adjusted / p['full_amount'], 2)
                p['full_amount'] = adjusted
            kept = [p for p in members if p['full_amount'] > 0.01]
            dropped.update(id(p) for p in members if p['full_amount'] <= 0.01)
            self._rs_spread_residual(kept, 'full_amount', class_gross - offset_gross)
            if vat_class == 'taxable':
                self._rs_spread_residual(kept, 'vat_amount', max(class_vat - offset_vat, 0.0))
        return [p for p in payloads if id(p) not in dropped]

    @staticmethod
    def _rs_vat_class(vat_amount):
        if vat_amount < 0:
            return 'untaxed'
        return 'taxable' if vat_amount > 0 else 'zero'

    def _rs_line_vat_class(self, line):
        taxes = line.tax_ids.flatten_taxes_hierarchy()
        classes = _rs_tax_vat_classes(taxes)
        if 'taxable' not in classes:
            return ('zero' if 'zero' in classes else 'untaxed'), 0.0
        if taxes.filtered(lambda t: t.ubl_cii_tax_category_code != RS_STANDARD_TAX_CATEGORY):
            AccountTax = self.env['account.tax']
            company = line.company_id or self.env.company
            base_line = line.move_id._prepare_product_base_line_for_taxes_computation(line)
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            vat = sum(
                data['tax_amount_currency']
                for data in base_line['tax_details']['taxes_data']
                if data['tax'].ubl_cii_tax_category_code == RS_STANDARD_TAX_CATEGORY
            )
        else:
            vat = (line.price_total or 0.0) - (line.price_subtotal or 0.0)
        return 'taxable', line.currency_id.round(abs(vat))

    def _rs_spread_residual(self, payloads, key, target):
        """Gives the cents that per-line rounding left to the largest lines first."""
        residual = self._rs_round(target - sum(p[key] for p in payloads), 2)
        for payload in sorted(payloads, key=lambda p: p[key], reverse=True):
            if abs(residual) < 0.01:
                break
            new_value = self._rs_round(max(payload[key] + residual, 0.0), 2)
            residual = self._rs_round(residual - (new_value - payload[key]), 2)
            payload[key] = new_value

    def _rs_line_to_payload(self, line):
        move = line.move_id or self
        raw_full = move._rs_amount_to_gel(line.price_total or 0)
        raw_qty = line.quantity or 0
        if move.move_type in ('out_invoice', 'in_invoice'):
            if raw_full < -0.01 or raw_qty < -0.0001:
                raise UserError(_(
                    "Line '%s' has a negative amount or quantity "
                    "(qty=%.4f, total=%.2f). rs.ge cannot accept "
                    "negative values on a regular invoice.\n\n"
                    "What to do:\n"
                    "• Split the document so the negative movement is "
                    "on a separate credit note.\n"
                    "• Or, if the line is an internal rounding/offset "
                    "that must not reach rs.ge, mark this document "
                    "as 'Skip rs.ge'.",
                    line.rs_einv_goods or '—', raw_qty, raw_full,
                ))
        full_amount = abs(raw_full)
        vat_class, vat = move._rs_line_vat_class(line)
        classes = _rs_tax_vat_classes(line.tax_ids.flatten_taxes_hierarchy())
        if len(classes) > 1:
            _logger.warning("Line %s of %s mixes VAT classes %s; rs.ge gets %s.", line.id, move.display_name, sorted(classes), vat_class)
        if vat_class == 'taxable':
            vat_amount = abs(move._rs_amount_to_gel(vat))
        else:
            vat_amount = 0.0 if vat_class == 'zero' else -1
        unit_name = (line.product_uom_id.name or '').strip() if line.product_uom_id else ''
        return {
            'goods': line.rs_einv_goods or '',
            'g_unit': unit_name or 'ერთეული',
            'qty': abs(raw_qty),
            'full_amount': full_amount,
            'vat_amount': vat_amount,
        }

    def _rs_amount_to_gel(self, amount):
        self.ensure_one()
        if not amount:
            return 0.0
        if not self.currency_id or self.currency_id == self.company_currency_id:
            return amount
        return self.company_currency_id.round(amount / self.invoice_currency_rate)

    def _rs_line_matches_slot(self, payload, slot):
        """True when the slot already matches, so the caller skips a save that would be a no-op."""
        if not isinstance(slot, dict):
            return False

        slot_goods = (slot.get('goods') or '').strip()
        slot_unit = (slot.get('g_unit') or '').strip()
        slot_qty = round(rs_to_float(slot.get('g_number')), 4)
        slot_full = round(rs_to_float(slot.get('full_amount')), 2)
        slot_vat = round(rs_to_float(slot.get('drg_amount')), 2)

        p_goods = (payload.get('goods') or '').strip()
        p_unit = (payload.get('g_unit') or '').strip()
        p_qty = round(float(payload.get('qty') or 0), 4)
        p_full = round(float(payload.get('full_amount') or 0), 2)
        p_vat = round(float(payload.get('vat_amount') or 0), 2)

        return (slot_goods == p_goods and slot_unit == p_unit and slot_qty == p_qty and slot_full == p_full and slot_vat == p_vat)

    def _rs_get_purchase_vat_18(self):
        """Maps the Default Purchase Tax through the bill's fiscal position, as core does."""
        tax = self.fiscal_position_id.map_tax(self.company_id.account_purchase_tax_id)
        if len(tax) == 1 and tax.ubl_cii_tax_category_code == RS_STANDARD_TAX_CATEGORY and not tax.price_include:
            return tax
        return self.env['account.tax']

    def _rs_pulled_line_vals(self, snap, purchase_vat_18, existing_line=None):
        """Discount is 0 because the rs.ge price is net; rs_line_id keys the next merge."""
        qty = snap.g_number or (existing_line.quantity if existing_line else 0.0) or 1.0
        full = snap.full_amount or 0.0
        vat = snap.drg_amount or 0.0
        if vat > 0 and purchase_vat_18:
            unit_price = ((full - vat) / qty) if qty else 0.0
            tax_cmd = [Command.set([purchase_vat_18.id])]
        else:
            unit_price = (full / qty) if qty else 0.0
            tax_cmd = [Command.clear()]
        vals = {
            'name': snap.goods or (existing_line.name if existing_line else False) or 'rs.ge import',
            'quantity': qty,
            'price_unit': unit_price,
            'discount': 0.0,
            'tax_ids': tax_cmd,
            'rs_line_id': snap.rs_line_id or False,
        }
        if not (existing_line and existing_line.product_id):
            product = self._rs_find_product_for_pulled(snap)
            if product:
                vals['product_id'] = product.id
        return vals

    def _rs_find_product_for_pulled(self, snap):
        """Name match; rs_base_methods overrides this to try the linked waybill's barcode first."""
        name = (snap.goods or '').strip()
        Product = self.env['product.product']
        if not name:
            return Product
        return Product.search([('name', '=ilike', name), *Product._check_company_domain(self.company_id)], limit=1)

    def _rs_log_untaxed_pulled_lines(self, snaps, purchase_vat_18):
        """Without a standard-rate purchase tax, rs.ge VAT lines come in untaxed at the gross price."""
        names = [snap.goods or 'unnamed' for snap in snaps if snap.drg_amount > 0]
        if names and not purchase_vat_18:
            self._rs_log("No standard-rate (S) Default Purchase Tax for %d line(s) (Accounting settings, or none left after the bill's fiscal "
                "position) — imported as untaxed (price = gross). Lines: %s. Set it, then click Reimport Lines." % (len(names), ', '.join(names[:3])),
                'warning')

    def _rs_auto_import_pulled_to_bill_lines(self):
        self.ensure_one()
        if not self.rs_einv_pulled_line_ids:
            return

        purchase_vat_18 = self._rs_get_purchase_vat_18()
        line_commands = [Command.create(self._rs_pulled_line_vals(snap, purchase_vat_18)) for snap in self.rs_einv_pulled_line_ids]

        if line_commands:
            self.write({'invoice_line_ids': line_commands, 'rs_einv_pulled_lines_hash': self._rs_pulled_lines_hash()})
            self._rs_log("Auto-imported %d line(s) from rs.ge into bill." % len(line_commands))
        self._rs_log_untaxed_pulled_lines(self.rs_einv_pulled_line_ids, purchase_vat_18)

    def _rs_refresh_pulled_lines(self, service, raise_on_failure=False):
        """Stores rs.ge lines as rs_pulled snapshots, to compare with the Odoo bill."""
        self.ensure_one()
        if not self.rs_einv_id:
            return
        try:
            rs_rows = service.get_invoice_desc(self._rs_inv_id_int)
        except Exception as e:
            _logger.warning("Could not fetch rs.ge lines for move %s (rs_id=%s): %s", self.id, self.rs_einv_id, e)
            if raise_on_failure:
                raise UserError(_("Could not read the rs.ge lines (rs.ge ID: %(rs_id)s).\n\nDetails: %(err)s", rs_id=self.rs_einv_id, err=e))
            return
        if not rs_rows:
            if raise_on_failure and self.rs_einv_pulled_line_ids:
                raise UserError(_("rs.ge returned no lines for %s. Try again in a moment.", self.display_name))
            return
        vals_list = [{
            'move_id': self.id,
            'snapshot_type': 'rs_pulled',
            **self._rs_line_snapshot_vals(row),
        } for row in rs_rows if isinstance(row, dict)]
        if vals_list:
            old_lines = self.rs_einv_pulled_line_ids
            self.env['rs.einvoice.correction.line'].create(vals_list)
            old_lines.unlink()

    def _rs_line_snapshot_vals(self, row):
        return {
            'rs_line_id': row.get('id') or '',
            'goods': row.get('goods') or '',
            'g_unit': row.get('g_unit') or '',
            'g_number': rs_to_float(row.get('g_number')),
            'full_amount': rs_to_float(row.get('full_amount')),
            'drg_amount': rs_to_float(row.get('drg_amount')),
        }

    def _rs_extract_inv_id(self, result):
        if not self._rs_save_succeeded(result):
            return None
        inv_id = getattr(result, 'invois_id', None)
        if inv_id and inv_id > 0:
            return inv_id
        return None

    def _rs_extract_k_id(self, result):
        k_id = getattr(result, 'k_id', None)
        if k_id and k_id > 0:
            return k_id
        return None

    def action_rs_view_current_data(self):
        self.ensure_one()
        if not self.rs_einv_id:
            raise UserError(_("This document has no rs.ge invoice ID yet — there is nothing to fetch from rs.ge."))
        wizard = self.env['rs.einvoice.view.wizard']._build_from_move(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _('rs.ge Invoice Data'),
            'res_model': 'rs.einvoice.view.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
