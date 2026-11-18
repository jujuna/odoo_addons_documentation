from odoo import models, fields, _
from odoo.exceptions import LockError, UserError
from markupsafe import Markup
import base64
import logging

_logger = logging.getLogger(__name__)


class RsWaybill(models.Model):
    _inherit = 'rs.waybill'


    def action_open_sales_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sales_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    def action_open_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.purchase_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    def action_open_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


    def action_open_mapping_wizard(self):
        """ Open the product mapping wizard for this waybill, pre_loaded with the lines that need a product or a unit """

        self.ensure_one()
        unresolved_lines = self.line_ids.filtered(lambda line: line.unresolved or line.uom_review)
        if not unresolved_lines:
            raise UserError(_('No unresolved lines found for this waybill.'))
        wizard =  self.env['rs.waybill.mapping.wizard'].create({
            'waybill_id': self.id,
            'line_ids': [(0, 0, {
                'line_id': line.id,
                'external_barcode': line.external_barcode or line.bar_code,
                'external_name': line.external_name or line.name,
                'product_id': line.product_id.id,
                'uom_id': line.uom_id.id if line.product_id else False,
            }) for line in unresolved_lines],
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Resolve Unresolved Goods'),
            'res_model': 'rs.waybill.mapping.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }


    def action_view_adjustments(self):
        """ Fetch adjustment history from RS and open it in a wizard popup. """
        self.ensure_one()
        if not self.rs_internal_id:
            raise UserError(_("This waybill has no RS.GE ID — no adjustments to view."))

        service = self._rs_service()
        adjustments = service.get_adjusted_waybills(self.rs_internal_id)
        if not adjustments:
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'message': _("This waybill has no adjustments on RS.GE yet."), 'type': 'info'}}

        wizard = self.env['rs.waybill.adjustment.wizard'].create({'waybill_id': self.id,
                                                                  'line_ids': [(0, 0, {
                                                                      'archival_id': adj['archival_id'],
                                                                      'date': adj['date'],
                                                                      'user_name': adj['user_name'],
                                                                  }) for adj in adjustments],
                                                                  })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rs.waybill.adjustment.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }


    def _rs_lock(self):
        """ Hold this waybill for one RS.GE call that must not run twice (a double click, two users): the other request
            is refused, not queued. Re-reads the waybill, which the first request may just have changed. """
        self.ensure_one()
        try:
            self.lock_for_update()
        except LockError:
            raise UserError(_("Waybill %s is already being sent to RS.GE. Wait a moment and reload "
                              "the page.") % self.display_name) from None
        self.invalidate_recordset()


    def action_save_to_rs(self):
        """ Send the waybill to RS.GE. A partly reserved delivery is split first: it keeps exactly what the waybill
            declares, the unreserved rest goes to a backorder with its own waybill. """
        self.ensure_one()
        if not self.rs_internal_id:
            # A first Save creates the waybill on RS.GE: a second Save at the same moment would create another.
            self._rs_lock()
        self._validate_before_save()
        picking = self.picking_id

        # Only 'at_confirm': other reservation methods unreserve the picking after a split, leaving this waybill empty.
        if (picking and self.waybill_direction == 'seller' and picking.state == 'assigned'
                and picking.picking_type_id.reservation_method == 'at_confirm'
                and any(m.uom_id.compare(m.quantity, m.product_uom_qty) < 0
                        for m in picking.move_ids if m.state not in ('done', 'cancel'))):
            picking.action_split_transfer()
        service = self._rs_service()
        result = service.save_waybill(self)

        if result.get('goods'):
            self._sync_rs_good_ids(result['goods'])
        # A sub-waybill is created off an active distribution, so RS activates it on save: mirror that (status 1).
        # Normal waybills stay draft until separately activated.
        is_sub = bool(self.parent_waybill_id)
        self.write({'rs_internal_id': int(result['id']),
                    'rs_needs_resave': False,
                    'rs_waybill_number': result['waybill_number'],
                    'state': 'active' if is_sub else 'draft',
                    'waybill_status': '1' if is_sub else '0'})
        self.env.cr.commit()
        self._rs_post_commit(_("Create the linked Odoo documents"),
                             self._rs_create_documents_if_missing)

        # Sub-waybill auto-activates on save and RS stamps its own BEGIN: mirror it by stamping transport_start_date,
        # trans_postpone_date, delivery_date to NOW so _check_delivery_after_start on Complete sees a consistent state.
        if is_sub:
            now = fields.Datetime.now()
            self.write({'transport_start_date': now,
                        'trans_postpone_date': now,
                        'delivery_date': now,})
            self._rs_post_commit(_("Update the parent distribution's remainder"),
                                 self.parent_waybill_id._refresh_distribution_remainder)


    def action_send_rs_waybill(self):
        self.ensure_one()
        self._rs_lock()
        if self.state == 'active':
            # A second click that waited for the first: already activated, nothing to send.
            return
        self._validate_before_save()
        if not self.rs_internal_id:
            self.action_save_to_rs()
            self._rs_lock()  # the save committed, which released the lock
        service = self._rs_service()
        service.send_waybill(self.rs_internal_id)
        self.write({'state': 'active', 'waybill_status': '1'})
        self.env.cr.commit()
        self._rs_post_commit(_("Create the linked Odoo documents"),self._rs_create_documents_if_missing)
        try:
            header, _goods = service.get_full_waybill(self.rs_internal_id)
            if header:
                self.write(self._map_rs_waybill_vals(header))
                self._sync_driver_name_to_partner()
            if self.parent_waybill_id and self.transport_start_date:
                self.delivery_date = self.transport_start_date
            self._set_default_delivery_date()
            # Sync Transport Start Date Postpone to the actual transport start (RS BEGIN, fetched above).
            if self.transport_start_date:
                self.trans_postpone_date = self.transport_start_date
            self._send_notification_email()
        except Exception as e:
            _logger.warning("Enrichment failed for waybill %s; drift cron will repair: %s", self.id, e)


    def action_edit_waybill(self):
        """ Open the waybill in a modal popup to edit; 'Submit Changes to RS.ge' then sends the adjustment. """
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_("Cancelled waybills cannot be edited."))
        if not self.rs_internal_id:
            raise UserError(_("This waybill is not yet on RS.GE — use Save instead."))
        if self.rs_goods_pending_snapshot:
            # The delivery does not follow the lines yet: an Adjustment now would hit it once and again on the retry.
            raise UserError(_("A goods change made on RS.GE is not applied to the delivery "
                              "yet. Fix the cause and click Retry first."))
        if self.rs_adjustment_error and not self.edit_snapshot_json:
            # Lines never reloaded after an Adjustment sent elsewhere: reload them before a new one starts from them
            self.action_discard_adjustment()

        # Snapshot the line state so action_submit_edit_to_rs can diff what changed and decide side effects.
        # After a refusal the lines hold the unsent changes: keep the snapshot of what RS.GE has.
        if not (self.rs_adjustment_error and self.edit_snapshot_json):
            self.edit_snapshot_json = self._build_line_snapshot()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Waybill'),
            'res_model': 'rs.waybill',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, edit_mode=True),
        }


    def action_submit_edit_to_rs(self):
        """ Edit an active/completed waybill; RS archives the previous state (get_adjusted_waybill(archival_id))
            and rs_internal_id stays the same. """
        self.ensure_one()
        self._rs_lock()
        if self.state == 'cancelled':
            raise UserError(_("Cancelled waybills cannot be edited."))
        if not self.rs_internal_id:
            raise UserError(_("This waybill is not yet on RS.GE — use Save instead."))
        if not self.edit_snapshot_json:
            # The popup saved its lines before this call: put them back as RS.GE has them, or the sync would push them to the delivery
            try:
                with self.env.cr.savepoint():
                    self.action_discard_adjustment()
            except Exception as e:
                # Not reloaded: hold the saved lines like a refused Adjustment, so no sync applies them to the delivery
                reason = str(e) or type(e).__name__
                self.rs_adjustment_error = self.env._("Another click or user sent an Adjustment first, and reloading the waybill from RS.GE "
                    "failed (%s): click Discard Adjustment to reload it.", reason)
                self.env.cr.commit()
                raise UserError(self.rs_adjustment_error) from e
            self.env.cr.commit()
            raise UserError(self.env._("This Adjustment was already sent to RS.GE by another click or user, "
                "so the waybill was reloaded as RS.GE has it: click Adjustment to change it again."))

        # Send to RS.GE inside a savepoint: a refusal undoes this method's changes on the delivery and order, keeps what
        # the popup saved, and says why.
        try:
            with self.env.cr.savepoint():
                corrections = self._rs_send_adjustment()
        except Exception as e:
            reason = str(e) or type(e).__name__
            self.rs_adjustment_error = reason
            self.env.cr.commit()
            raise UserError(_("The Adjustment was not sent to RS.GE: %s\nYour changes are kept in Odoo "
                              "only. Fix the cause and click Submit again, or Discard Adjustment to "
                              "go back to the waybill as it is on RS.GE.") % reason) from e
        self.rs_adjustment_error = False
        self.env.cr.commit()
        service = self._rs_service()

        try:
            header, goods = service.get_full_waybill(self.rs_internal_id)
            if header:
                self.write(self._map_rs_waybill_vals(header))
            if goods:
                self._sync_goods_lines(goods)
            self.message_post(body=_("Waybill edited. RS archived previous state — view via 'Adjustments'."))
            self._send_notification_email(action='Edited')
        except Exception as e:
            _logger.warning("Enrichment failed for waybill %s; drift cron will repair: %s", self.id, e)

        if corrections:
            return self.action_reconcile_pending_return()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Waybill Edited'),
                'message': _('Waybill %s was updated on RS.ge. Previous version archived as adjustment.') % (
                        self.rs_waybill_number or self.rs_internal_id),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


    def action_discard_adjustment(self):
        """ Banner button: drop an unsent Adjustment by reloading the waybill as it is on RS.GE (header and goods);
            the delivery and order were never changed by it. """
        self.ensure_one()
        header, goods = self._rs_service().get_full_waybill(self.rs_internal_id)
        if not header:
            raise UserError(_("RS.GE could not be reached, so the waybill was not reloaded. Try "
                              "again in a moment."))
        self.write(self._map_rs_waybill_vals(header))
        self.write({'rs_adjustment_error': False, 'edit_snapshot_json': False})
        self._sync_goods_lines(goods)
        self.message_post(body=_("Adjustment discarded: the waybill was reloaded from RS.GE."))


    def _rs_send_adjustment(self):
        """ Part of action_submit_edit_to_rs up to the RS.GE save, in its savepoint: updates delivery / order,
            then sends the waybill. Returns the goods lowered off a completed waybill (for the popup). """
        self._validate_before_save()

        corrections = []
        diffs = self._compute_line_diff(self.edit_snapshot_json)
        picking_state = self.picking_id.state if self.picking_id else 'no-picking'
        if diffs:
            _logger.info("[EDIT DIFF] Waybill %s — picking state: %s, %d line change(s)",
                         self.id, picking_state, len(diffs))
            for d in diffs:
                _logger.info("[EDIT DIFF]   %-9s  product_id=%s  %s → %s (qty_diff=%s)",
                             d['type'], d['product_id'], d['old_qty'], d['new_qty'], d['qty_diff'])

            if self.picking_id and self.picking_id.state == 'done':
                # DONE branch. qty_down / removed: buyer received LESS, so the done delivery is lowered in place (no
                # return waybill: the RS.GE adjustment is the proof) and kept pending until the popup is answered.
                corrections = self._rs_lower_done_delivery(self._qty_to_return_from_diffs(diffs))
                if self.waybill_type == '5':
                    # A return lowered: its receipt is lowered, nothing went back to a shelf to ask about.
                    corrections = []
                self._rs_add_pending_corrections(corrections)
                # qty_up / added: buyer received MORE. One physical movement was under-documented, so the SAME done
                # delivery is corrected (moves bumped or extended) instead of a second waybill; qty_delivered follows.
                self._apply_line_diffs_increase_on_done(diffs)
                self._rs_refresh_return_question()
            elif self.picking_id:
                self._apply_line_diffs_to_picking_in_place(diffs)
        else:
            _logger.info("[EDIT DIFF] Waybill %s — no line changes (metadata-only edit)", self.id)
        self._sync_buyer_to_so_and_picking()
        self.edit_snapshot_json = False

        service = self._rs_service()
        # Lines removed in the edit are tombstoned on RS (STATUS=-1), else RS keeps the good and the re-fetch re-creates
        # the line. Only lines that already had an RS good id.
        removed_good_ids = [
            d['snap']['rs_good_id']
            for d in diffs
            if d['type'] == 'removed' and d.get('snap')
               and str(d['snap'].get('rs_good_id') or '').strip() not in ('', '0')
        ]
        result = service.save_waybill(self, removed_good_ids=removed_good_ids)
        if result.get('goods'):
            self._sync_rs_good_ids(result['goods'])

        vals = {}
        if self.is_confirmed == '1':
            vals['is_buyer_reconfirm_needed'] = True
        if vals:
            self.write(vals)
        return corrections


    def action_update_rs_status(self):
        self.ensure_one()
        if not self.rs_internal_id:
            raise UserError(_("This waybill has no RS.GE ID."))
        service = self._rs_service()
        header, goods = service.get_full_waybill(self.rs_internal_id)
        if not header:
            raise UserError(_("Could not fetch waybill from RS.GE."))
        was_completed = self.state == 'completed'
        was_confirmed = self.is_confirmed == '1'
        was_cancelled = self.state == 'cancelled'
        vals = self._map_rs_waybill_vals(header)
        self.with_context(rs_from_rs=True).write(vals)
        self._sync_driver_name_to_partner()
        self._sync_buyer_to_so_and_picking()
        goods_snapshot = self._build_line_snapshot()
        self._sync_goods_lines(goods)
        self._apply_rs_goods_diff_auto(goods_snapshot)
        if not was_completed and self.state == 'completed':
            self._cascade_validate_picking()
        if not was_confirmed and self.is_confirmed == '1':
            self._rs_post_commit(_("Validate the incoming receipt"), self._cascade_validate_receipt)
        if not was_cancelled and self.state == 'cancelled':
            self._cascade_cancel_purchase()
            self._cascade_cancel_delivery()
        # Buyer: seller edited the waybill → our Receive was reset, ask to receive again.
        if (self.waybill_direction == 'buyer' and was_confirmed
                and self.is_confirmed != '1' and not self.is_buyer_reconfirm_needed):
            self.is_buyer_reconfirm_needed = True
            self.message_post(body=Markup(_("Seller edited this waybill on RS.GE — your previous Receive was reset. "
                                            "Review the changes and click <b>Receive</b> again (or <b>Reject</b>).")))
        if (not self.picking_id and not self.purchase_id
                and self.state != 'cancelled' and self._in_integration_scope()):
            if self.waybill_direction in ('buyer', 'seller'):
                self._rs_build_documents()


    def _check_delivery_after_start(self):
        """RS rejects a close unless delivery is strictly AFTER transport start: refuse it here before Complete.
        Distribution subs and distribution parents (type 4) are exempt: RS allows start == delivery."""
        self.ensure_one()
        if self.parent_waybill_id or self.waybill_type == '4':
            return
        start = self.transport_start_date or self.activation_date
        if self.delivery_date and start and self.delivery_date <= start:
            raise UserError(_("Delivery Date cannot be equal to or earlier than the "
                              "Transport Start Date. Please set a later Delivery Date."))

    def _clamp_future_delivery_date(self):
        """RS rejects a close with a future delivery date (close_waybill_vd -> -1): clamp it to now."""
        self.ensure_one()
        if self.delivery_date and self.delivery_date > fields.Datetime.now():
            self.delivery_date = fields.Datetime.now()

    def _close_on_rs(self, service):
        """Close on RS; with a delivery date use close_waybill_vd, and if RS rejects it (-1, e.g. a just-completed sub)
        fall back to plain close_waybill (RS records its own time)."""
        self.ensure_one()
        if self.delivery_date:
            # Ask for the raw code to fall back only on the -1 delivery-window rejection; credential (-100),
            # wrong-taxpayer (-101), other codes and transport failures must surface.
            code = service.close_waybill_vd(self.rs_internal_id, self.delivery_date, check=False)
            if code == 1:
                return
            if code != -1:
                service._check_rs_result('close_waybill_vd', code)
            _logger.warning("close_waybill_vd rejected the delivery date for waybill %s "
                            "(-1, delivery vs begin/current); closing with RS current "
                            "time instead", self.id)
        service.close_waybill(self.rs_internal_id)

    def _set_default_delivery_date(self):
        """On activation, default delivery date to the transport start: invalid for completion (RS needs AFTER start),
        so the operator must enter a real one. The drift cron writes delivery_date only when RS has one."""
        self.ensure_one()
        if not self.delivery_date:
            self.delivery_date = self.transport_start_date or fields.Datetime.now()

    def action_close_waybill(self):
        self.ensure_one()
        self._check_delivery_after_start()
        self._clamp_future_delivery_date()
        service = self._rs_service()
        self._rs_create_documents_if_missing()
        # Check before RS closes the waybill: after the close the mismatch can't be undone.
        picking = self.picking_id
        if picking and self.waybill_direction == 'seller' and picking.state not in ('done', 'cancel'):
            picking._rs_check_waybill_qty()

        if self.waybill_type == '3':
            if not self.rs_internal_id:
                self.action_save_to_rs()
            if self.state == 'draft':
                service.send_waybill(self.rs_internal_id)
                self.write({'state':'active', 'waybill_status': '1'})
                self.env.cr.commit()
            # Type 3 has no Activate button (draft -> active -> completed here). The create-documents call at the top
            # ran while draft (reverse-create skips); build the SO + delivery for the close cascade. No-op if linked.
            self._rs_post_commit(_("Create the linked Odoo documents"),self._rs_create_documents_if_missing)
            # Type 3: delivery-confirmation fields are hidden on the draft form and carried by the initial save,
            # so do NOT re-save before closing (a save on a just-activated waybill makes RS flag it "adjusted").
            self._close_on_rs(service)
            self.write({'state': 'completed', 'waybill_status': '2'})
            self.env.cr.commit()
            try:
                header, _goods = service.get_full_waybill(self.rs_internal_id)
                if header:
                    self.write(self._map_rs_waybill_vals(header))
                self._send_notification_email()
            except Exception as e:
                _logger.warning("Enrichment failed for waybill %s; drift cron will repair: %s", self.id, e)
            self._rs_post_commit(_("Validate the linked transfer"),self._cascade_validate_picking)
            return


        if not self.rs_internal_id:
            raise UserError(_("Please save the waybill to RS.GE first."))
        # Close via close_waybill_vd (delivery date) or plain close. No save first: RS flags it "adjusted" after a save;
        # plain close has no reception params: changed Handed Over / Received By / Notes go through Adjustment.
        self._close_on_rs(service)
        self.write({'state': 'completed', 'waybill_status': '2'})
        self.env.cr.commit()
        try:
            header, _goods = service.get_full_waybill(self.rs_internal_id)
            if header:
                self.write(self._map_rs_waybill_vals(header))
            self._send_notification_email()
        except Exception as e:
            _logger.warning("Enrichment failed for waybill %s; drift cron will repair: %s", self.id, e)
        self._rs_post_commit(_("Validate the linked transfer"),self._cascade_validate_picking)


    def action_refuse_waybill(self):
        self.ensure_one()
        self._require_rs_id()
        if self.waybill_type == '4' and not self.parent_waybill_id:
            return self._rs_cancel_distribution()
        if self.state == 'completed':
            # The goods left: RS.GE corrects a completed waybill, it is never cancelled.
            raise UserError(_("Waybill %s is completed: the goods were delivered, so it cannot be cancelled. "
                              "Use Adjustment to correct the quantities, or Return on the delivery if goods "
                              "came back.") % self.display_name)
        service = self._rs_service()
        service.refuse_waybill(self.rs_internal_id)
        vals = {'state': 'cancelled',
                'waybill_status': '-2',
                'cancel_date': fields.Datetime.now()}
        if (self.waybill_direction == 'seller' and self.picking_id
                and self.picking_id.state not in ('done', 'cancel')):
            # Committed with the cancel: if the request dies before the delivery and the
            # order follow (_cascade_cancel_delivery below), the drift job finishes them.
            vals['rs_cancel_cascade'] = 'pending'
        self.write(vals)
        self.env.cr.commit()
        self._cascade_cancel_delivery()
        # Sub-waybill cancelled → its reserved quantity returns to the parent, and
        # its linked Sales Order is cancelled too (distribution sub; internal sub has none).
        if self.parent_waybill_id:
            if self.sales_order_id and self.sales_order_id.state != 'cancel':
                self._rs_post_commit(_("Cancel the linked sales order"),
                                     self.sales_order_id.with_context(skip_rs_auto_create=True).action_cancel)
            self._rs_post_commit(_("Update the parent distribution's remainder"),
                                 self.parent_waybill_id._refresh_distribution_remainder)
        try:
            self._send_notification_email(action='Refused')
        except Exception as e:
            _logger.warning("Email failed for waybill %s; will retry later: %s", self.id, e)


    def _rs_cancel_distribution(self):
        """ Cancel a distribution waybill (active/completed): one RS.GE cancel cascades to all subs. If RS refuses while
            subs are live, cancel active subs first, retry once. Odoo then marks all cancelled (sub cancel rule). """
        service = self._rs_service()
        comment = self.comment or _('Cancelled')
        try:
            service.ref_waybill_vd(self.rs_internal_id, comment=comment)
        except UserError:
            active_subs = self.sub_waybill_ids.filtered(
                lambda s: s.rs_internal_id and s.state == 'active')
            if not active_subs:
                raise
            for sub in active_subs:
                sub._rs_service().refuse_waybill(sub.rs_internal_id)
            service.ref_waybill_vd(self.rs_internal_id, comment=comment)
        now = fields.Datetime.now()
        cancelled = self | self.sub_waybill_ids.filtered(lambda s: s.state != 'cancelled')
        for waybill in cancelled:
            vals = {'state': 'cancelled', 'waybill_status': '-2', 'cancel_date': now}
            if (waybill.waybill_direction == 'seller' and waybill.picking_id
                    and waybill.picking_id.state not in ('done', 'cancel')):
                vals['rs_cancel_cascade'] = 'pending'
            waybill.write(vals)
        self.env.cr.commit()
        for waybill in cancelled:
            waybill._cascade_cancel_delivery()
        self.message_post(body=_("Distribution cancelled on RS.GE with its %s sub-waybill(s).") % (len(cancelled) - 1))
        try:
            self._send_notification_email(action='Refused')
        except Exception as e:
            _logger.warning("Email failed for waybill %s; will retry later: %s", self.id, e)


    def action_delete_waybill(self):
        self.ensure_one()
        self._require_rs_id()
        picking = self.picking_id  # capture before unlink (the M2o becomes False after)
        service = self._rs_service()
        result = service.delete_waybill(self.rs_internal_id)
        if not result:
            raise UserError(_("RS.GE refused to delete this waybill."))
        name = self.display_name
        self.with_context(rs_deleted_on_rs=True).unlink()
        # RS.GE has deleted it: keep it deleted here too, whatever happens next.
        self.env.cr.commit()
        # Reverse cascade: cancel the linked delivery; the waybill is already unlinked, so action_cancel skips it.
        if picking and picking.state not in ('cancel', 'done'):
            try:
                with self.env.cr.savepoint():
                    picking.action_cancel()
            except Exception as e:
                _logger.warning("Delivery %s not cancelled after its waybill was deleted: %s", picking.name, e)
                note = _("Waybill %(waybill)s was deleted on RS.GE, but this delivery could not "
                         "be cancelled: %(error)s. Cancel it by hand.") % {'waybill': name, 'error': e}
                picking.message_post(body=note)
                picking.activity_schedule('mail.mail_activity_data_todo',
                                          summary=_("Cancel this delivery: its waybill was deleted"),
                                          note=note, user_id=self.env.user.id)


    def action_confirm_waybill(self):
        # Block Receive while a goods line is unmapped: confirming would set is_confirmed on RS but build no PO/receipt.
        if len(self) == 1 and self.waybill_direction == 'buyer':
            n = sum(1 for l in self.line_ids if l.unresolved)
            if n:
                raise UserError(_("Map the products first — %s goods line(s) still need a product "
                                  "(click 'Resolve Now'). Receiving now would create no purchase order "
                                  "or receipt.") % n)
            n = sum(1 for l in self.line_ids if l.uom_review)
            if n:
                raise UserError(_("Pick the unit first — %s goods line(s) are marked 'Unit Needs Review': RS.GE's "
                                  "unit matches none or several of the product's units, so receiving now could book "
                                  "the goods in the wrong unit.") % n)
        if len(self) == 1 and self.waybill_direction == 'buyer' and self.waybill_type in ('2', '3', '4'):
            if self.rs_needs_purchase_pick:
                raise UserError(_("Pick the purchase order these goods belong to first (banner "
                                  "on top of the waybill)."))
            if self.purchase_id and self.purchase_id.state != 'purchase':
                raise UserError(_("Purchase order %s is not confirmed (it may wait for approval). "
                                  "Approve it first.") % self.purchase_id.name)
        confirmed = 0
        skipped = 0
        for record in self:
            # Skip already-confirmed (no re-confirm pending), and any buyer waybill
            # that still has unresolved lines (bulk 'Mark as Received' safety net).
            if not record.rs_internal_id or (record.is_confirmed == '1' and not record.is_buyer_reconfirm_needed):
                skipped += 1
                continue
            if record.waybill_direction == 'buyer' and any(l.unresolved or l.uom_review for l in record.line_ids):
                skipped += 1
                continue
            if record.rs_needs_purchase_pick or (
                    record.purchase_id and record.purchase_id.state != 'purchase'):
                skipped += 1
                continue
            try:
                # RS first, stock after: the RS confirmation is the fact the goods are ours. Receiving on the PO
                # is a post-commit step retried by the drift job, never undoing it. Each waybill uses its own login.
                record._rs_service().confirm_waybill(record.rs_internal_id)
                record.write({'is_confirmed': '1', 'is_buyer_reconfirm_needed': False,
                              'pending_goods_json': False})
                self.env.cr.commit()
                record._rs_post_commit(_("Validate the incoming receipt"),
                                       record._cascade_validate_receipt)
                try:
                    record._send_notification_email(action='Confirmed')
                except Exception as e:
                    _logger.warning("Email failed for waybill %s: %s", record.id, e)
                confirmed += 1
            except Exception as e:
                if len(self) == 1:
                    raise
                _logger.warning("Failed to confirm waybill %s: %s", record.rs_internal_id, e)
                skipped += 1

        if len(self) > 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Confirm Complete',
                    'message': f'{confirmed} confirmed, {skipped} skipped.',
                    'type': 'success',
                    'sticky': False,
                }
            }


    def action_reject_waybill(self):
        self.ensure_one()
        self._require_rs_id()
        service = self._rs_service()
        service.reject_waybill(self.rs_internal_id)
        # Rejecting does NOT apply the vendor's change: PO and receipt stay untouched and diverge from the waybill. KEEP
        # pending_goods_json (drives the "vendor changed goods" banner); a later Receive reconciles live and clears it.
        had_pending = bool(self.pending_goods_json)
        self.write({'is_confirmed': '2'})
        self.env.cr.commit()
        msg = _("Waybill rejected on RS.GE. PO and receipt remain open — buyer may still "
                "reconsider and click Receive, or the seller may edit or cancel.")
        if had_pending:
            msg += _(" The vendor's goods change was NOT applied — the waybill no longer "
                     "matches the PO. Clicking Receive later will apply it.")
        self.message_post(body=msg)
        try:
            self._send_notification_email(action='Rejected')
        except Exception as e:
            _logger.warning("Email failed for waybill: %s", e)


    def action_reconcile_pending_return(self):
        """ 'Reconcile Delivery': open the correction popup for goods lowered off this delivered waybill (Adjustment or
            RS.GE change). The delivery is already lowered; the popup decides where goods are and what the order does,
            then clears the flag. """
        self.ensure_one()
        entries = self._rs_load_pending_corrections()
        if not entries:
            # Clear and say so: raising would roll the clearing back and the banner would stay.
            self.pending_return_json = False
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'message': _("Nothing left to reconcile on this waybill."), 'type': 'info',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}
        return self._open_return_decision_wizard(entries)


    def action_send_carrier_waybill(self):
        """ Carrier 'Send to Transporter': save_waybill with STATUS=8 (Sent-to-Transporter), no waybill_number; the
            transporter activates via send_waybill_transporter. Must NOT call send_waybill (it activates). """
        self.ensure_one()
        self._rs_lock()
        if self.waybill_status == '8':
            # A second click that waited for the first: already with the transporter.
            return
        self._validate_before_save()
        service = self._rs_service()
        # _build_waybill_xml reads self.waybill_status: set 8 before the SOAP call so the XML carries STATUS 8.
        self.waybill_status = '8'
        result = service.save_waybill(self)
        if result.get('goods'):
            self._sync_rs_good_ids(result['goods'])
        self.write({'rs_internal_id': int(result['id']),
                    'state': 'draft',
                    'waybill_status': '8',})
        self.env.cr.commit()
        self._rs_post_commit(_("Create the linked Odoo documents"), self._rs_create_documents_if_missing)
        try:
            self._send_notification_email(action='Sent to Transporter')
        except Exception as e:
            _logger.warning("Email failed for waybill %s: %s", self.id, e)


    def action_save_transporter(self):
        self.ensure_one()
        self._require_rs_id()
        self._validate_transporter_driver_fields()
        service = self._rs_service()
        service.save_transporter_waybill(waybill_id=self.rs_internal_id,
                                         car_number=self.car_number or '',
                                         driver_tin=self.driver_tin or '',
                                         driver_name=self.driver_name or '',
                                         trans_id=int(self.transport_type) if self.transport_type else 1,
                                         trans_txt=self.other_transport or '',
                                         chek_driver_tin=0 if self.driver_is_foreigner else 1,
                                         reception_info=self.reception_info or '',
                                         receiver_info=self.receiver_info or '',)


    def action_active_transporter(self):
        self.ensure_one()
        self._require_rs_id()
        self._validate_transporter_driver_fields()
        service = self._rs_service()
        waybill_number = service.send_transporter_waybill(self.rs_internal_id, self.trans_postpone_date or fields.Datetime.now(),)
        self.write({'rs_waybill_number': waybill_number,
                    'state': 'active',
                    'waybill_status': '1'})
        self.env.cr.commit()
        try:
            self._send_notification_email(action='Transport Activated')
        except Exception as e:
            _logger.warning("Email failed for waybill %s; will retry later: %s", self.id, e)


    def action_close_transporter(self):
        self.ensure_one()
        self._require_rs_id()
        service = self._rs_service()
        service.close_transporter_waybill(waybill_id=self.rs_internal_id,
                                          delivery_date=self.delivery_date or fields.Datetime.now(),
                                          reception_info=self.reception_info or '',
                                          receiver_info=self.receiver_info or '',)
        self.write({'state': 'completed',
                    'waybill_status': '2'})
        self.env.cr.commit()
        try:
            self._send_notification_email(action='Transport Completed')
        except Exception as e:
            _logger.warning("Email failed for waybill %s; will retry later: %s", self.id, e)


    def action_create_sub_waybill(self):
        """ Distribution sub-waybill carved from this type-4 parent: on RS a Distribution (type 4) linked via PAR_ID;
        its 'sub-waybill' identity is parent_waybill_id, not the RS type. """
        return self._create_sub_waybill('4')

    def action_create_sub_waybill_internal_trans(self):
        """ Internal-transport (type 1) sub-waybill carved from this type-4 parent. """
        return self._create_sub_waybill('1')

    def _create_sub_waybill(self, sub_type):
        self.ensure_one()
        if self.waybill_type != '4':
            raise UserError(_("Sub-waybills can only be created from a Distribution (type 4) waybill."))
        if not self.rs_internal_id:
            raise UserError(_("Save the distribution waybill to RS.GE first."))
        line_cmds = []
        for line in self.line_ids:
            available = self._sub_available(line)
            line_cmds.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'bar_code': line.bar_code,
                'unit_name': line.unit_name,
                'uom_id': line.uom_id.id,
                'unit_price': line.unit_price,
                'vat_type': line.vat_type,
                'quantity': 0.0,
                'parent_remaining': available,
                'remainder_quantity': available,
            }))
        # Default the sub's transport start and delivery date to the parent's start (RS allows start == delivery).
        # trans_postpone_date is shown as "Transport Start Date" and has a now() default, so set it explicitly too.
        sub_start = self.transport_start_date or fields.Datetime.now()
        sub = self.create({
            'waybill_direction': 'seller',
            'waybill_type': sub_type,
            'parent_waybill_id': self.id,
            'category': self.category,
            'seller_tin': self.seller_tin,
            'seller_name': self.seller_name,
            'start_address': self.start_address,
            'transport_start_date': sub_start,
            'trans_postpone_date': sub_start,
            'delivery_date': sub_start,
            'company_id': self.company_id.id,
            'line_ids': line_cmds,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sub-Waybill'),
            'res_model': 'rs.waybill',
            'res_id': sub.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_remainder_waybill(self):
        """ Create a SEPARATE Distribution waybill for the undistributed leftover: copies header + transport, no buyer,
            goods = remaining qty per line, linked via remainder_origin_id (no PAR_ID); Save builds a return transfer.
            Does not consume the remainder; several allowed. """
        self.ensure_one()
        if self.waybill_type != '4' or self.parent_waybill_id or self.remainder_origin_id:
            raise UserError(_("Remainder waybills can only be created from a Distribution waybill."))
        line_cmds = []
        for line in self.line_ids:
            remaining = self._sub_available(line)
            if remaining <= 0:
                continue
            line_cmds.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'bar_code': line.bar_code,
                'unit_name': line.unit_name,
                'uom_id': line.uom_id.id,
                'unit_price': line.unit_price,
                'vat_type': line.vat_type,
                'quantity': remaining,
            }))
        if not line_cmds:
            raise UserError(_("Nothing left to put on a remainder waybill — everything is distributed."))
        remainder = self.create({
            'waybill_direction': 'seller',
            'waybill_type': '4',
            'remainder_origin_id': self.id,
            'category': self.category,
            'seller_tin': self.seller_tin,
            'seller_name': self.seller_name,
            'start_address': self.start_address,
            'transport_type': self.transport_type,
            'driver_tin': self.driver_tin,
            'driver_name': self.driver_name,
            'car_number': self.car_number,
            'company_id': self.company_id.id,
            'line_ids': line_cmds,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remainder Waybill'),
            'res_model': 'rs.waybill',
            'res_id': remainder.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _sub_available(self, parent_line):
        """Quantity left on a parent distribution line: its quantity minus what non-cancelled subs saved on RS
        (with rs_internal_id) reserved; drops on Save, restored if the sub is cancelled."""
        self.ensure_one()
        key = (parent_line.bar_code or '', parent_line.name or '')
        distributed = sum(
            sl.quantity or 0.0
            for sub in self.sub_waybill_ids.filtered(
                lambda s: s.rs_internal_id and s.state != 'cancelled')
            for sl in sub.line_ids.filtered(lambda l: (l.bar_code or '', l.name or '') == key)
        )
        return (parent_line.quantity or 0.0) - distributed

    def _refresh_distribution_remainder(self):
        """On the parent distribution: set each line's remainder to quantity minus
        everything distributed by completed sub-waybills."""
        self.ensure_one()
        for pline in self.line_ids:
            pline.remainder_quantity = self._sub_available(pline)

    def action_open_record_form(self):
        """ Open this waybill's own full-page form (a sub opens full-page from the parent's list, not in a dialog). """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.rs_waybill_number or _('Sub-Waybill'),
            'res_model': 'rs.waybill',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_parent_waybill(self):
        """ Sub-waybill 'Main Waybill' button → open the parent distribution. """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Distribution Waybill'),
            'res_model': 'rs.waybill',
            'res_id': self.parent_waybill_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_subwaybill_complete(self):
        """ Sub-waybill 'Complete': save if needed, activate + close on RS, then write back the parent's remaining qty.
            RS stamps start and delivery to NOW on this click: mirrored locally before save
            (the 'delivery > start' check is off for subs). """
        self.ensure_one()
        if not self.parent_waybill_id:
            raise UserError(_("This is not a sub-waybill."))
        # Stamp all three date fields to NOW, as RS does on this click (trans_postpone_date = "Transport Start Date").
        now = fields.Datetime.now()
        self.write({'transport_start_date': now,
                    'trans_postpone_date': now,
                    'delivery_date': now,
                    })
        self._validate_before_save()
        self._check_delivery_after_start()
        self._clamp_future_delivery_date()
        service = self._rs_service()
        if not self.rs_internal_id:
            self.action_save_to_rs()
        # Activate + close with the regular calls; the VD/date variants are only needed for an explicit delivery date.
        if self.state != 'active':
            service.send_waybill(self.rs_internal_id)
            self.write({'state': 'active', 'waybill_status': '1'})
            self.env.cr.commit()
        self._close_on_rs(service)
        self.write({'state': 'completed', 'waybill_status': '2'})
        self.env.cr.commit()
        self._rs_post_commit(_("Update the parent distribution's remainder"),
                             self.parent_waybill_id._refresh_distribution_remainder)
        # Mirror the RS close on the Odoo side: validate the linked delivery (distribution
        # sub) or internal transfer (internal-transport sub) so the goods actually move.
        self._rs_post_commit(_("Validate the linked transfer"), self._cascade_validate_picking)
        try:
            header, _goods = service.get_full_waybill(self.rs_internal_id)
            if header:
                self.write(self._map_rs_waybill_vals(header))
        except Exception as e:
            _logger.warning("Sub-waybill enrichment failed for %s: %s", self.id, e)
        return


    def action_print_pdf(self):
        self.ensure_one()
        self._require_rs_id()
        service = self._rs_service()
        pdf_data = service.get_print_pdf(self.rs_internal_id)
        if not pdf_data:
            raise UserError(_("No PDF returned from RS.GE"))

        name = 'Waybill_%s.pdf' % (self.rs_waybill_number or self.rs_internal_id)
        raw = pdf_data if isinstance(pdf_data, bytes) else base64.b64decode(pdf_data)
        # One PDF per waybill, refreshed with what RS.GE prints now (it changes after an Adjustment).
        attachment = self.env['ir.attachment'].search([('res_model', '=', self._name), ('res_id', '=', self.id),
                                                       ('name', '=', name)], limit=1)
        if attachment:
            attachment.raw = raw
        else:
            attachment = self.env['ir.attachment'].create({
                'name': name,
                'type': 'binary',
                'raw': raw,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'new',
        }
