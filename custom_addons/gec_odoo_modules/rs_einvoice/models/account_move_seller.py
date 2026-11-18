import logging

from odoo import models, fields, _
from odoo.exceptions import UserError

from .account_move import (_rs_status_label, rs_to_int, rs_to_float, RS_DRAFT_OR_NEW_CORRECTION, RS_ACCEPTED)
from .rs_soap_service import _TRANSIENT_EXCEPTIONS, _rs_row_lookup, _to_rs_dt

_logger = logging.getLogger(__name__)


class RsNoAnswerError(UserError):
    pass


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_rs_create(self):
        self.ensure_one()
        self._rs_acquire_row_lock(_('Send to RS'))
        if self.rs_einv_pending_action and not self.rs_einv_id:
            raise UserError(_(
                "A previous rs.ge request on this document is still pending "
                "(action: %(action)s, since: %(since)s). rs.ge may have "
                "already accepted it.\n\n"
                "Click 'Check Status' to check whether an ID arrived, or "
                "use 'Resolve Orphan' / 'Dismiss Pending' on the RS E-Invoice "
                "tab before retrying — otherwise a second Send to RS could "
                "create a duplicate rs.ge record.",
                action=self.rs_einv_pending_action,
                since=self.rs_einv_pending_action_at or '—',
            ))
        if self.rs_einv_skip:
            raise UserError(_("This document is marked 'Skip rs.ge', so it must not be sent to rs.ge. Untick Skip only if this is truly a VAT "
                "invoice/correction that belongs on rs.ge."))
        if self.move_type == 'out_invoice' and self.rs_einv_replaces_id:
            self._rs_assert_replacement_cancel_accepted()
        self._rs_validate()

        if self.rs_einv_id:
            raise UserError(_("This document is already on rs.ge (ID: %s). Use 'Update on RS' to push changes, or 'Check Status' to refresh the "
                "status.", self.rs_einv_id))

        service = self._rs_get_service(check_auth=True)
        if (self.move_type == 'out_invoice' and self.rs_einv_replaces_id and self.rs_einv_replacement_mode == 'correction'):
            self._rs_create_invoice_correction(service)
            return

        is_credit_note = self.move_type in ('out_refund', 'in_refund')
        original = self.reversed_entry_id

        if is_credit_note and original and original.rs_einv_id:
            raise UserError(_(
                "Sending a credit note to rs.ge is no longer supported.\n\n"
                "To correct an invoice on rs.ge, open the original invoice "
                "and use 'Add Credit Note → Replace RS invoice with a "
                "corrected invoice'. The replacement invoice carries the "
                "corrected lines directly; rs.ge receives the new state.\n\n"
                "If this credit note is books-only (bad debt, netting, "
                "warranty, intercompany mirror, etc.), tick 'Skip rs.ge' "
                "on the RS E-Invoice tab and pick the right skip reason."
            ))
        elif is_credit_note and not original:
            # rs.ge requires every credit to target one specific original.
            raise UserError(_(
                "This credit note is not linked to an original invoice, so "
                "rs.ge cannot accept it on its own.\n\n"
                "Pick one of the following:\n"
                "• Fill 'Reversal of:' with the original invoice this credit "
                "applies to. Every rs.ge correction must target one specific "
                "original.\n"
                "• If the credit covers several originals (volume rebate, "
                "year-end discount, etc.) split it into one credit note per "
                "original.\n"
                "• If the credit is VAT-neutral by design (bad debt, netting, "
                "warranty, intercompany mirror, etc.), tick 'Skip rs.ge' on "
                "the RS E-Invoice tab."
            ))
        elif is_credit_note and original and not original.rs_einv_id:
            raise UserError(_("The original invoice (%s) has not been sent to rs.ge yet, so there is nothing to correct. Send the original first, "
                "then return to this credit note.", original.display_name or original.name))
        else:
            self._rs_create_invoice(service)

    def _rs_create_invoice(self, service):
        seller_un_id = service._rs_company_un_id()
        buyer_un_id = service._rs_partner_un_id(self.partner_id)
        variant, note = self._rs_pick_save_variant()

        # Mark pending before the rs.ge request for orphan recovery.
        self._rs_mark_pending('create')

        result = service.save_invoice(inv_id=0, operation_date=_to_rs_dt(self.invoice_date or fields.Date.today()), seller_un_id=seller_un_id,
            buyer_un_id=buyer_un_id, variant=variant, note=note)
        inv_id = self._rs_extract_inv_id(result)
        if not inv_id:
            self._rs_log("Failed to create invoice on RS (variant=%s): %s" % (variant, result), 'error')
            raise UserError(_("rs.ge did not return an invoice ID — the document was not created. See the RS Logs at the bottom of this tab and try "
                "again."))

        self.rs_einv_id = str(inv_id)
        self.rs_einv_status = '0'
        self._rs_clear_pending()
        self._rs_log("Created on RS with ID: %s (variant: %s). Header created; header/line sync will continue." % (inv_id, variant))

        self.env.cr.commit()

        move = self._rs_relock_after_commit()
        if not move:
            _logger.warning("Post-create line sync skipped for move %s (rs_id=%s): row busy or removed. Use Update on RS to finish syncing.", self.id,
                inv_id)
            return
        move._rs_sync_lines(service)
        move._rs_stamp_sync_hash()
        move._rs_sync_native_advance_settlements(service)

    @staticmethod
    def _rs_advance_response_status(result):
        status = _rs_row_lookup(result, 'Status', 'status')
        message = _rs_row_lookup(result, 'Message', 'message') or ''
        return str(status or ''), message

    def _rs_advance_datatable_error(self, rows, label):
        for row in rows or []:
            err = _rs_row_lookup(row, 'Error', 'error')
            err_msg = _rs_row_lookup(row, 'ErrorMessage', 'error_message', 'errormessage')
            if err or err_msg:
                raise UserError(_("rs.ge returned an error while reading %(label)s: %(err)s", label=label, err=err_msg or err))

    def _rs_line_vat_abs_gel(self, line):
        move = line.move_id or self
        return self._rs_round(abs(move._rs_amount_to_gel(move._rs_line_vat_class(line)[1])), 2)

    def _rs_move_vat_abs_gel(self, move):
        vat = 0.0
        for line in move._rs_product_lines():
            vat += abs(move._rs_amount_to_gel(move._rs_line_vat_class(line)[1]))
        return self._rs_round(vat, 2)

    def _rs_native_delivery_vat_total(self):
        self.ensure_one()
        total = 0.0
        for line in self._rs_product_lines().filtered(lambda l: not getattr(l, 'is_downpayment', False)):
            total += self._rs_line_vat_abs_gel(line)
        return self._rs_round(total, 2)

    def _rs_expected_advance_settlements(self, force=False):
        self.ensure_one()
        if not force and not self._rs_uses_native_advance_attach():
            return []
        line_model = self.env['account.move.line']
        if 'is_downpayment' not in line_model._fields:
            raise UserError(_("Native rs.ge advance settlement needs Odoo down-payment metadata, but account.move.line has no is_downpayment field."))
        offset_lines = self._rs_product_lines().filtered(lambda l: getattr(l, 'is_downpayment',
            False) and ((l.price_total or 0.0) < -0.01 or (l.quantity or 0.0) < -0.0001))
        if not offset_lines:
            raise UserError(_("Native rs.ge advance settlement could not find any negative down-payment offset lines on this invoice."))

        by_advance = {}
        for line in offset_lines:
            vat_amount = self._rs_line_vat_abs_gel(line)
            if vat_amount <= 0.0:
                raise UserError(_("Down-payment offset line '%s' has no VAT amount to settle on rs.ge.", line.name or '—'))
            if 'sale_line_ids' not in line._fields:
                raise UserError(_("Native rs.ge advance settlement needs the Sales link on down-payment offset lines, but this database does not "
                    "expose sale_line_ids on invoice lines."))
            sale_lines = line.sale_line_ids
            if not sale_lines:
                raise UserError(_("Down-payment offset line '%s' is not linked to a Sale Order line, so Odoo cannot identify the advance invoice "
                    "without parsing labels. Keep Advance Settlement as Net.", line.name or '—'))
            if 'invoice_lines' not in sale_lines._fields:
                raise UserError(_("Native rs.ge advance settlement cannot read prior invoice lines from the linked Sale Order line."))
            candidates = sale_lines.mapped('invoice_lines').mapped('move_id').filtered(
                lambda m: m
                and m != self
                and m.move_type == 'out_invoice'
                and m.state == 'posted'
                and m.company_id == self.company_id
                and m.partner_id == self.partner_id
                and m.rs_einv_is_advance
            )
            if not candidates:
                raise UserError(_("Could not find a posted Odoo advance invoice linked to down-payment offset line '%s'. Send/mark the advance "
                    "invoice first, or use Net mode.", line.name or '—'))
            offset_vat = self._rs_line_vat_class(line)[1]
            if len(candidates) > 1:
                exact = candidates.filtered(
                    lambda m: abs(self._rs_move_vat_abs_gel(m) - self._rs_round(abs(m._rs_amount_to_gel(offset_vat)), 2)) <= 0.01)
                if len(exact) == 1:
                    candidates = exact
                else:
                    raise UserError(_("Down-payment offset line '%(line)s' is linked to %(count)d possible advance invoices. Odoo cannot safely "
                        "decide which rs.ge advance to attach.", line=line.name or '—', count=len(candidates)))
            advance = candidates[0]
            if not advance.rs_einv_id:
                raise UserError(_("Advance invoice %(advance)s is not on rs.ge yet. Send the advance to rs.ge before using native settlement.",
                    advance=advance.display_name or advance.name or '—'))
            if not str(advance.rs_einv_id).isdigit():
                raise UserError(_("Advance invoice %(advance)s has an invalid rs.ge ID: %(rs_id)s.",
                    advance=advance.display_name or advance.name or '—', rs_id=advance.rs_einv_id))
            settle_gel = self._rs_round(abs(advance._rs_amount_to_gel(offset_vat)), 2)
            item = by_advance.setdefault(advance.id,
                {'advance_move': advance, 'advance_rs_id': int(advance.rs_einv_id), 'vat_amount': 0.0, 'offset_line_ids': []})
            item['vat_amount'] = self._rs_round(item['vat_amount'] + settle_gel, 2)
            item['offset_line_ids'].append(line.id)
        return list(by_advance.values())

    def _rs_build_advance_audit_vals(self, item, status, message, action):
        return {
            'final_move_id': self.id,
            'advance_move_id': item['advance_move'].id,
            'advance_rs_id': str(item['advance_rs_id']),
            'vat_amount': item['vat_amount'],
            'rs_status': str(status or ''),
            'rs_message': message or '',
            'action': action,
            'synced_at': fields.Datetime.now(),
        }

    def _rs_check_native_advance_eligibility(self, final_date):
        self.ensure_one()
        settlement_model = self.env['rs.einvoice.advance.settlement']
        chain_ids = self.ids
        if self.rs_einv_replacement_mode == 'correction':
            chain_ids = chain_ids + self.rs_einv_replaces_id.ids
        for item in self._rs_expected_advance_settlements():
            advance = item['advance_move']
            if settlement_model.search_count([('final_move_id', 'in', chain_ids), ('advance_move_id', '=', advance.id), ('rs_status', '=', '200')]):
                continue
            adv_date = advance.invoice_date
            if adv_date and (adv_date.year, adv_date.month) >= (final_date.year, final_date.month):
                raise UserError(_("Advance invoice %(advance)s is dated %(adv)s. rs.ge only attaches advances from a month strictly earlier than the "
                    "final invoice's month (%(final)s) — a same-month advance is covered by the final invoice itself. Use Net mode, or date this "
                    "invoice in a later month.", advance=advance.display_name or advance.name, adv='%04d-%02d' % (adv_date.year, adv_date.month),
                    final='%04d-%02d' % (final_date.year, final_date.month)))
            if advance.rs_einv_status not in RS_ACCEPTED:
                raise UserError(_("Advance invoice %(advance)s is not buyer-confirmed on rs.ge (status: %(status)s). rs.ge only attaches confirmed "
                    "advances — ask the buyer to confirm it, click Check Status on the advance, then retry.",
                    advance=advance.display_name or advance.name, status=_rs_status_label(advance.rs_einv_status)))

    def _rs_native_advance_eligible(self):
        self.ensure_one()
        if (self.move_type != 'out_invoice' or self.rs_einv_is_advance or not self._rs_has_downpayment_offset_lines()):
            return False
        try:
            items = self._rs_expected_advance_settlements(force=True)
        except UserError:
            return False
        if not items:
            return False
        final_date = self.invoice_date or fields.Date.context_today(self)
        for item in items:
            advance = item['advance_move']
            adv_date = advance.invoice_date
            if adv_date and (adv_date.year, adv_date.month) >= (final_date.year, final_date.month):
                return False
            if advance.rs_einv_status not in RS_ACCEPTED and advance.rs_einv_id:
                try:
                    advance._rs_safe_refresh_status()
                except UserError:
                    pass
            if advance.rs_einv_status not in RS_ACCEPTED:
                return False
        return True

    def _rs_diagnose_unattachable(self, service, item, period_date):
        status = ''
        try:
            live = service.get_invoice(item['advance_rs_id'])
            status = str(getattr(live, 'status', '') or '')
        except Exception as e:
            _logger.warning("Could not read advance %s for diagnosis: %s", item['advance_rs_id'], e)
        if status and status not in RS_ACCEPTED:
            return _("the advance is not buyer-confirmed on rs.ge (status: %s). Ask the buyer to confirm it first.", _rs_status_label(status))
        adv_date = item['advance_move'].invoice_date
        if adv_date and (adv_date.year, adv_date.month) >= (period_date.year, period_date.month):
            return _("its operation month (%(adv)s) is not strictly earlier than this invoice's month (%(final)s) — rs.ge never attaches same-month "
                "advances.", adv='%04d-%02d' % (adv_date.year, adv_date.month), final='%04d-%02d' % (period_date.year, period_date.month))
        return _("it is confirmed and earlier-month, so it is most likely fully settled or under correction — check it on rs.ge.")

    def _rs_advance_settlement_usage(self, service):
        self.ensure_one()
        finals = self.env['rs.einvoice.advance.settlement'].search([
            ('advance_move_id', '=', self.id),
            ('rs_status', '=', '200'),
        ]).mapped('final_move_id').filtered('rs_einv_id')
        usage = []
        for final in finals:
            try:
                rows = service.get_attached_advance_invoices(final._rs_inv_id_int) or []
            except Exception as e:
                _logger.warning("Advance usage check skipped for final %s: %s", final.id, e)
                continue
            for row in rows:
                advance_id = rs_to_int(_rs_row_lookup(row, 'INVOICE_ADVANCE_ID', 'invoice_advance_id', 'advance_invoice_id'))
                if str(advance_id) == str(self.rs_einv_id):
                    usage.append({
                        'final': final,
                        'used': rs_to_float(_rs_row_lookup(row, 'TOTAL_USED', 'total_used')),
                        'left': rs_to_float(_rs_row_lookup(row, 'AMOUNT_LEFT', 'amount_left')),
                    })
        return usage

    def _rs_assert_advance_correctable(self, service, replacement=None):
        self.ensure_one()
        if not self.rs_einv_is_advance:
            return
        usage = self._rs_advance_settlement_usage(service)
        if not usage:
            return
        if any(u['left'] <= 0.005 for u in usage):
            raise UserError(_("rs.ge refuses corrections of a fully settled advance invoice. This advance VAT is fully consumed by: %s. To change "
                "the advance, the consuming invoice must first be cancelled on rs.ge so the advance is released.",
                ', '.join(u['final'].display_name or u['final'].name or '—' for u in usage)))
        if replacement is not None:
            used = max(u['used'] for u in usage)
            new_vat = self._rs_move_vat_abs_gel(replacement)
            if new_vat < used - 0.01:
                raise UserError(_("The corrected advance VAT (%(new).2f GEL) is below the VAT already settled on final invoices (%(used).2f GEL). "
                    "rs.ge refuses this — first reduce the settled amount on the "
                    "final invoice(s), or keep the advance VAT at %(used).2f GEL or more.", new=new_vat, used=used))

    def _rs_sync_native_advance_settlements(self, service, target_id=None):
        """Never raises; returns True on full success and False on any failure."""
        self.ensure_one()
        if not self._rs_uses_native_advance_attach():
            if self.rs_einv_advance_sync_state:
                self.rs_einv_advance_sync_state = False
            return True

        audit_rows = []
        error_message = None
        remote_writes = 0
        target_id = target_id or self._rs_inv_id_int

        try:
            if not target_id:
                raise UserError(_("Native rs.ge advance settlement needs an rs.ge invoice ID. Click Send to RS first."))

            expected = self._rs_expected_advance_settlements()
            delivery_vat = self._rs_native_delivery_vat_total()
            expected_vat = self._rs_round(sum(item['vat_amount'] for item in expected), 2)
            if expected_vat > delivery_vat + 0.01:
                raise UserError(_("Native advance settlement would attach %(advance).2f GEL VAT, but the full delivery VAT is only %(delivery).2f "
                    "GEL. This would over-settle the rs.ge invoice.", advance=expected_vat, delivery=delivery_vat))

            seller_un_id = service._rs_company_un_id()
            buyer_tin = (self.partner_id.vat or '').strip()
            period_date = self.invoice_date or fields.Date.today()
            period_date = period_date.replace(day=1)
            attachable_rows = service.get_attachable_advance_invoices(seller_un_id=seller_un_id, buyer_tin=buyer_tin,
                operation_date=period_date) or []
            attached_rows = service.get_attached_advance_invoices(target_id) or []
            self._rs_advance_datatable_error(attachable_rows, _("attachable advances"))
            self._rs_advance_datatable_error(attached_rows, _("attached advances"))

            attachable_ids = {rs_to_int(_rs_row_lookup(row, 'ID', 'id')) for row in attachable_rows}
            attached_by_id = {}
            for row in attached_rows:
                advance_id = rs_to_int(_rs_row_lookup(row, 'INVOICE_ADVANCE_ID', 'invoice_advance_id', 'advance_invoice_id'))
                if advance_id:
                    attached_by_id[advance_id] = row

            expected_ids = {item['advance_rs_id'] for item in expected}
            stray = [row for advance_id, row in attached_by_id.items() if advance_id not in expected_ids]
            if stray:
                raise UserError(_(
                    "rs.ge has advance(s) attached to this invoice that Odoo "
                    "does not expect: %s. They were carried over from the "
                    "corrected original or attached on the rs.ge portal. "
                    "rs.ge refuses detaching a confirmed advance during a "
                    "correction — re-add the matching down-payment offset "
                    "line(s), or use Cancel & Reissue.",
                    ', '.join(
                        '%s (VAT %.2f)' % (
                            _rs_row_lookup(row, 'F_SERIES', 'f_series')
                            or _rs_row_lookup(
                                row, 'INVOICE_ADVANCE_ID',
                                'invoice_advance_id'),
                            rs_to_float(_rs_row_lookup(
                                row, 'DRG_AMOUNT', 'drg_amount')),
                        ) for row in stray
                    ),
                ))

            for item in expected:
                advance_id = item['advance_rs_id']
                amount = item['vat_amount']
                attached = attached_by_id.get(advance_id)
                if attached:
                    current = self._rs_round(rs_to_float(_rs_row_lookup(attached, 'DRG_AMOUNT', 'drg_amount')), 2)
                    if abs(current - amount) <= 0.01:
                        audit_rows.append(self._rs_build_advance_audit_vals(item, '200', _("Already attached on rs.ge"), 'already'))
                        continue
                    min_floor = rs_to_float(_rs_row_lookup(attached, 'MIN_DRG_AMOUNT', 'min_drg_amount'))
                    if min_floor > 0 and amount < min_floor - 0.01:
                        raise UserError(_("Advance %(advance)s: rs.ge will not let the settled VAT drop below %(floor).2f GEL on this correction "
                            "(the amount settled before it). Odoo expects %(amount).2f GEL — adjust the down-payment offset line.",
                            advance=advance_id, floor=min_floor, amount=amount))
                    if self.rs_einv_status not in ('0', '1', '4', '5'):
                        audit_rows.append(self._rs_build_advance_audit_vals(item, '',
                            _("Cannot update: rs.ge status %s blocks the advance change") % _rs_status_label(self.rs_einv_status), 'updated'))
                        raise UserError(_("Advance %(advance)s is already attached on rs.ge with VAT %(current).2f, but Odoo expects %(expected).2f. "
                            "rs.ge only allows updating attached advances while the invoice is Draft/Sent/New Correction/Correction Sent.",
                            advance=advance_id, current=current, expected=amount))
                    result = service.update_advance_invoice(invoice_id=target_id, advance_invoice_id=advance_id, advance_invoice_drg_amount=amount)
                    status, message = self._rs_advance_response_status(result)
                    audit_rows.append(self._rs_build_advance_audit_vals(item, status, message, 'updated'))
                    if status != '200':
                        raise UserError(_("rs.ge refused to update advance %(advance)s on invoice %(invoice)s: %(message)s", advance=advance_id,
                            invoice=target_id, message=message or status or result))
                    remote_writes += 1
                    continue

                if advance_id not in attachable_ids:
                    raise UserError(_("Advance rs.ge invoice %(advance)s is expected from Odoo, but rs.ge did not return it as attachable for seller "
                        "%(seller)s, buyer TIN %(buyer)s, period %(period)s: %(reason)s", advance=advance_id, seller=seller_un_id, buyer=buyer_tin,
                        period=period_date, reason=self._rs_diagnose_unattachable(service, item, period_date)))
                result = service.attach_advance_invoice(invoice_id=target_id, advance_invoice_id=advance_id, advance_invoice_drg_amount=amount,
                    seller_un_id=seller_un_id, buyer_tin=buyer_tin)
                status, message = self._rs_advance_response_status(result)
                audit_rows.append(self._rs_build_advance_audit_vals(item, status, message, 'attached'))
                if status != '200':
                    raise UserError(_("rs.ge refused to attach advance %(advance)s to invoice %(invoice)s: %(message)s", advance=advance_id,
                        invoice=target_id, message=message or status or result))
                remote_writes += 1

        except UserError as e:
            error_message = e.args[0] if e.args else str(e)
        except Exception as e:
            error_message = _("Native advance settlement failed: %s") % e

        if audit_rows:
            self.env['rs.einvoice.advance.settlement'].create(audit_rows)
        if error_message:
            self.rs_einv_advance_sync_state = 'partial' if remote_writes else 'error'
            self._rs_log(error_message, 'error')
            return False
        self.rs_einv_advance_sync_state = 'synced'
        total_vat = sum(row['vat_amount'] for row in audit_rows)
        self._rs_log("Native advance settlement synced: %d advance(s), VAT %.2f GEL" % (len(audit_rows), total_vat))
        return True

    def _rs_assert_correction_can_be_sent(self):
        self.ensure_one()
        original = self.rs_einv_replaces_id
        if not original or not original.rs_einv_id:
            raise UserError(_("Cannot send this replacement as a correction — the invoice it replaces (%s) is not on rs.ge. Send the original first, "
                "then retry.", (original.display_name if original else '—') or '—'))
        if self.partner_id != original.partner_id:
            raise UserError(_(
                "Correct & Reissue cannot change the buyer. The replacement "
                "invoice's partner (%(new)s) differs from the original's "
                "partner (%(orig)s).\n\n"
                "Use Cancel & Reissue to close the old rs.ge chain and "
                "issue a fresh invoice to the new buyer.",
                new=self.partner_id.display_name or '—',
                orig=original.partner_id.display_name or '—',
            ))

        original._rs_safe_refresh_status()
        blocker = original._rs_find_pending_correction_blocker(exclude_move=self)
        if blocker:
            raise UserError(_(
                "Another correction is already in progress on rs.ge for "
                "the invoice this replacement targets:\n"
                "  • Document: %s\n"
                "  • rs.ge ID: %s\n"
                "  • Status:   %s\n\n"
                "Finish or delete it on rs.ge, then send this replacement.",
                blocker.display_name or blocker.name or '—',
                blocker.rs_einv_id or '—',
                _rs_status_label(blocker.rs_einv_status),
            ))
        original._rs_assert_chain_has_local_confirmed_correction()
        return original

    def _rs_create_invoice_correction(self, service):
        self.ensure_one()
        original = self._rs_assert_correction_can_be_sent()
        original._rs_assert_advance_correctable(service, replacement=self)
        if (not self._rs_uses_native_advance_attach()
                and self.env['rs.einvoice.advance.settlement'].search_count([
                    ('final_move_id', '=', original.id),
                    ('rs_status', '=', '200'),
                ])):
            raise UserError(_("The invoice being corrected has advances attached on rs.ge, and rs.ge carries them onto the correction automatically. "
                "Keep Advance Settlement = 'Native rs.ge advance settlement' and the down-payment offset line(s) on this replacement so Odoo "
                "reconciles them, or use Cancel & Reissue."))
        k_type_str = self.rs_einv_k_type or '3'
        k_type = int(k_type_str)
        reason_label = dict(self._fields['rs_einv_k_type'].selection).get(k_type_str, k_type_str)
        if not self.rs_einv_k_type:
            self.rs_einv_k_type = k_type_str

        base_id = original._rs_get_correction_base_id()
        self._rs_mark_pending('correction')
        result = service.create_correction(base_id, k_type=k_type)
        k_id = self._rs_extract_k_id(result)
        if not k_id:
            self._rs_log("Replacement correction create failed (base=%s, reason=%s): %s" % (base_id, reason_label, result), 'error')
            msg = _("rs.ge did not return a correction ID — the replacement correction was not created. See the RS Logs at the bottom of this tab "
                "and try again.")
            if original.rs_einv_is_advance:
                msg += _(" Note: rs.ge refuses corrections of a fully settled advance — if this advance is attached to a delivery invoice (possibly "
                    "on the rs.ge portal), release it first.")
            raise UserError(msg)

        self.rs_einv_id = str(k_id)
        self.rs_einv_status = '4'
        self._rs_clear_pending()
        variant, _note_ignored = self._rs_pick_save_variant()
        self._rs_log("Replacement correction created: %s (base=%s, reason=%s, "
            "type=%s, original=%s). Header created; header/line sync will continue." % (k_id, base_id, reason_label, variant, original.rs_einv_id))
        self.env.cr.commit()
        move = self._rs_relock_after_commit()
        if not move:
            _logger.warning("Post-correction sync skipped for move %s (k_id=%s): row busy or removed. Use Update on RS to finish syncing.", self.id,
                k_id)
            return
        move._rs_push_header_to_rs(service, target_id=k_id, label="corrected replacement ID %s" % k_id)
        move._rs_sync_lines(service)
        move._rs_stamp_sync_hash()


    def action_rs_edit(self):
        self.ensure_one()
        self._rs_acquire_row_lock(_('Update on RS'))
        if not self.rs_einv_id:
            raise UserError(_("This document is not on rs.ge yet. Click 'Send to RS' first."))
        if self.state != 'posted' and not (self.state == 'draft' and self._rs_is_sale_correction()):
            raise UserError(_("Post the invoice before updating it on rs.ge."))
        self._rs_safe_refresh_status()

        if self.rs_einv_status in ('0', '1', '4'):
            target_id = self._rs_inv_id_int
            target_label = "invoice %s" % self.rs_einv_id
        else:
            raise UserError(_("Cannot update this document — rs.ge status is now '%s'. If the buyer already confirmed it, use 'Add Credit Note' to "
                "create a correction instead.", _rs_status_label(self.rs_einv_status)))

        self._rs_validate()
        service = self._rs_get_service(check_auth=True)

        sending_correction = self._rs_target_is_correction(target_id)
        push_header = (self.rs_einv_status != '1' and (self.move_type not in ('out_refund', 'in_refund') or sending_correction))
        if push_header:
            self._rs_push_header_to_rs(service, target_id, label=target_label)

        self._rs_sync_lines(service, target_id=target_id)
        self._rs_stamp_sync_hash()
        self._rs_sync_native_advance_settlements(service, target_id=target_id)
        if self.rs_einv_rejection_note:
            self.rs_einv_rejection_note = False
        self._rs_log("Updated lines on RS (%s)" % target_label)

    def action_rs_delete(self):
        self.ensure_one()
        self._rs_acquire_row_lock(_('Delete on RS'))
        if not self.rs_einv_id:
            raise UserError(_("This document is not on rs.ge yet — nothing to delete."))

        self._rs_safe_refresh_status()

        if self.rs_einv_status not in RS_DRAFT_OR_NEW_CORRECTION:
            raise UserError(_("You can only delete a record while its rs.ge status is 'Draft' or 'New Correction'. Current status: '%s'. If it is "
                "already sent to the buyer, use 'Cancel on RS' instead.", _rs_status_label(self.rs_einv_status)))

        service = self._rs_get_service(check_auth=True)
        old_id = self.rs_einv_id
        delete_result = service.delete_invoice(int(old_id))
        _logger.info("delete_invoice(%s) returned: %s", old_id, delete_result)

        if not delete_result:
            self._rs_log("Failed to delete on RS: %s" % delete_result, 'error')
            raise UserError(_("rs.ge refused to delete the document (ID: %s). See the RS Logs at the bottom of this tab for details.", old_id))

        result = service.get_invoice(int(old_id))
        rs_status = str(getattr(result, 'status', ''))
        if rs_status and rs_status != '-1':
            self._rs_log("Delete called but rs.ge still reports status %s "
                "(expected -1). Local pointer kept to avoid orphaning the RS record." % rs_status, 'error')
            raise UserError(_(
                "rs.ge accepted the delete call but the document still "
                "shows status '%s' (expected: Deleted).\n\n"
                "This usually means rs.ge is returning stale data — wait a "
                "minute, click Check Status, then try Delete on RS again.\n\n"
                "The Odoo RS Invoice ID was NOT cleared — clearing it now "
                "would leave a live document on rs.ge that we cannot find again.",
                _rs_status_label(rs_status),
            ))

        self._rs_log("Deleted from RS (ID: %s)" % old_id)

        self.with_context(rs_allow_id_overwrite=True).write({
            'rs_einv_id': False,
            'rs_einv_status': False,
            'rs_einv_last_sync_hash': False,
        })

        parent = self._rs_chain_parent()
        if parent and parent.rs_einv_id:
            try:
                orig_result = service.get_invoice(parent._rs_inv_id_int)
                new_orig_status = str(getattr(orig_result, 'status', ''))
                if new_orig_status and new_orig_status != parent.rs_einv_status:
                    old = parent.rs_einv_status
                    parent.rs_einv_status = new_orig_status
                    parent._rs_log("Status reverted by correction deletion: %s -> %s" % (old, new_orig_status))
            except Exception as e:
                _logger.warning("Could not refresh original after correction delete: %s", e)

    def action_rs_send(self):
        self.ensure_one()
        self._rs_acquire_row_lock(_('Send to buyer'))
        if self.move_type == 'out_invoice' and self.rs_einv_replaces_id:
            self._rs_assert_replacement_cancel_accepted()
        if not self.rs_einv_id:
            raise UserError(_("This document is not on rs.ge yet. Click 'Send to RS' first."))
        if self.state != 'posted' and not (self.state == 'draft' and self._rs_is_sale_correction()):
            raise UserError(_("Post the invoice before sending it to the buyer on rs.ge."))

        self._rs_safe_refresh_status()

        if self.rs_einv_status in RS_DRAFT_OR_NEW_CORRECTION:
            target_id = self._rs_inv_id_int
        else:
            raise UserError(_("You can only send a record that is in 'Draft' or 'New Correction'. Current rs.ge status: '%s'.",
                _rs_status_label(self.rs_einv_status)))

        self._rs_validate()
        service = self._rs_get_service(check_auth=True)
        sending_correction = self._rs_target_is_correction(target_id)
        if not self.move_type in ('out_refund', 'in_refund') or sending_correction:
            self._rs_push_header_to_rs(service, target_id, label=str(target_id))
        self._rs_sync_lines(service, target_id=target_id)
        self._rs_stamp_sync_hash()
        advance_ok = self._rs_sync_native_advance_settlements(service, target_id=target_id)
        if not advance_ok:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Advance attach blocked Send to buyer"),
                    'message': _("Advance settlement failed — check the Advance Settlements section and RS Logs."),
                    'type': 'danger',
                    'sticky': True,
                },
            }

        if sending_correction:
            send_result = service.send_correction(target_id)
            _logger.info("send_correction(%s) returned: %s", target_id, send_result)
        else:
            send_result = service.send_invoice(target_id)
            _logger.info("send_invoice(%s) returned: %s", target_id, send_result)

        if not self._rs_send_succeeded(send_result):
            self._rs_log("Failed to send to buyer (id=%s, correction=%s). RS returned: %s" % (target_id, sending_correction, send_result), 'error')
            raise UserError(_("rs.ge refused the send (rs.ge ID: %s). See the RS Logs at the bottom of this tab, or open the document directly on "
                "rs.ge to check the state.", target_id))

        expected_status = '5' if sending_correction else '1'
        label = "%s %s" % ("correction" if sending_correction else "invoice", self.rs_einv_id)
        if self.rs_einv_rejection_note:
            self.rs_einv_rejection_note = False
            self.rs_einv_rejection_status = False
        self.rs_einv_status = expected_status
        self.rs_einv_sent_at = fields.Datetime.now()
        self._rs_log("Sent %s to buyer (rs.ge accepted; expected status: %s)" % (label, expected_status))
        self.env.cr.commit()

        move = self._rs_relock_after_commit()
        if not move:
            _logger.info("Send verification skipped for move %s: row busy or removed.", self.id)
            return
        try:
            with self.env.cr.savepoint():
                result = service.get_invoice(target_id)
                _logger.info("get_invoice(%s) after send: %s", target_id, result)
                new_status, series, number = move._rs_extract_status_triplet(result)
                if series:
                    move.rs_einv_series = series
                if number:
                    move.rs_einv_number = number
                if (new_status and new_status != expected_status and move.rs_einv_status == expected_status):
                    move.rs_einv_status = new_status
                    move._rs_log("Send verification: rs.ge actually reports "
                        "status %s (expected %s). %s may need attention." % (new_status, expected_status, label), 'warning')
        except Exception as e:
            _logger.warning("Send verification read failed on move %s (rs_id=%s): %s. Local status stays at the acknowledged target.", self.id,
                self.rs_einv_id, e)
            move._rs_log("Send acknowledged but verification read failed: %s. Click Check Status if the actual rs.ge state looks off." % e,
                'warning')
        if sending_correction:
            parent = move._rs_chain_parent()
            if parent and parent.rs_einv_id and parent.id != move.id:
                try:
                    parent._rs_safe_refresh_status()
                except Exception as e:
                    _logger.warning("Could not refresh original %s after correction send on move %s: %s", parent.id, move.id, e)
                    move._rs_log("Correction sent, but refreshing the original (%s) "
                        "failed: %s. Click Check Status on it if its status looks stale." % (parent.display_name, e), 'warning')

    def action_rs_cancel(self):
        """Sets 6 for buyer confirmation; read-back other than 6 applies as Check Status; 7 cancels this document."""
        self.ensure_one()
        self._rs_acquire_row_lock(_('Cancel on RS'))
        service, target_id_str = self._rs_cancel_core()
        target_id = int(target_id_str)
        self.env.cr.commit()

        move = self._rs_relock_after_commit()
        if not move:
            _logger.info("Cancel verification skipped for move %s: row busy or removed.", self.id)
            return
        try:
            result = service.get_invoice(target_id)
            new_status = str(getattr(result, 'status', ''))
        except Exception as e:
            move._rs_log("Cancel committed locally as Cancelled (Sent) but verification read failed (target=%s): %s" % (target_id, e), 'warning')
            return
        if new_status and new_status != '6':
            move._rs_refresh_apply_status(new_status, move.rs_einv_status)

    def _rs_cancel_core(self):
        """No commit here: the caller commits, so Cancel-and-Reissue persists atomically."""
        self.ensure_one()
        if not self.rs_einv_id:
            raise UserError(_("This document is not on rs.ge yet — nothing to cancel."))

        self._rs_safe_refresh_status()

        pending = self._rs_find_pending_correction_blocker()
        if pending:
            raise UserError(_("A correction is in progress for this invoice (rs.ge ID: %s, status: '%s'). Finish or delete it before requesting "
                "cancellation.", pending.rs_einv_id, _rs_status_label(pending.rs_einv_status)))

        target_id_str = self.rs_einv_id
        target_status = self.rs_einv_status
        if not target_id_str:
            raise UserError(_("Nothing to cancel — no rs.ge record is linked to this document."))
        if target_status not in RS_ACCEPTED:
            raise UserError(_("Only confirmed or corrected records can be cancelled. Current rs.ge status: '%s'. If the document is sent but not yet "
                "confirmed, use 'Delete on RS' instead.", _rs_status_label(target_status)))

        target_id = int(target_id_str)

        service = self._rs_get_service(check_auth=True)
        try:
            cancel_result = service.cancel_invoice(target_id)
        except _TRANSIENT_EXCEPTIONS as e:
            msg = _("rs.ge did not answer the cancel request for %s. Click Check Status: if it shows Cancelled (Sent), the cancel went through; "
                "otherwise click Cancel on RS again.", self.display_name)
            if self.rs_einv_replaced_by_id.state == 'draft' and self.rs_einv_replaced_by_id.rs_einv_replacement_mode == 'fresh':
                msg += _(" The replacement draft %s is kept; it can be posted once the buyer confirms the cancellation.",
                    self.rs_einv_replaced_by_id.display_name)
            self._rs_notify(msg, 'error', post_chatter=True, activity_xmlid='mail.mail_activity_data_todo',
                activity_summary=_("Check the rs.ge cancellation"))
            raise RsNoAnswerError(msg) from e
        success = bool(getattr(cancel_result, 'change_invoice_statusResult', cancel_result))
        _logger.info("cancel_invoice(%s) returned: %s", target_id, cancel_result)

        if not success:
            self._rs_log("Failed to cancel on RS (target=%s): %s" % (target_id, cancel_result), 'error')
            raise UserError(_("rs.ge refused the cancellation (rs.ge ID: %s). See the RS Logs at the bottom of this tab.", target_id_str))

        self._rs_apply_status_update(target_id_str, '6', action_label=_('Cancel'))
        self._rs_schedule_cancel_pending_activity(target_id_str)
        return service, target_id_str

    def _rs_apply_status_update(self, target_id_str, new_status, action_label='Update'):
        if not target_id_str:
            return
        if not new_status:
            self._rs_log("%s accepted on RS but new status could not be read back (target: %s)." % (action_label, target_id_str), 'warning')
            return

        if str(self.rs_einv_id or '') == str(target_id_str):
            old = self.rs_einv_status
            self.rs_einv_status = new_status
            msg = _("%(action)s on RS (status: %(old)s → %(new)s)") % {
                'action': action_label,
                'old': _rs_status_label(old),
                'new': _rs_status_label(new_status),
            }
            self._rs_notify(msg, post_chatter=True)
