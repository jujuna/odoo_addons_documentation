from odoo import api, models, fields, _
from odoo.exceptions import UserError

from ..models.account_move import RS_SKIP_REASON


# Labels for K_TYPE in account_move.py; keep the codes in sync with it.
RS_K_TYPE_WIZARD = [
    ('1', 'Full cancellation'),
    ('2', 'Change tax treatment only (rare)'),
    ('3', 'Change price or amount'),
    ('4', 'Goods Returned to Seller'),
]


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    rs_einv_flow = fields.Selection([
        ('skip', 'Only correct Odoo, not rs.ge'),
        ('replace', 'Cancel old RS invoice and issue a new one'),
        ('correct_reissue', 'Replace RS invoice with a corrected invoice'),
    ], string='RS Treatment', help="Pick how this credit note interacts with rs.ge — Odoo-only, cancel-and-reissue, or correct-and-reissue.")
    rs_einv_k_type = fields.Selection(RS_K_TYPE_WIZARD, string='Reason for RS correction',
        help="Choose why this document is being corrected on rs.ge: price or amount change for discounts and amount corrections, goods returned when "
        "items physically came back, tax treatment only for rare VAT classification changes, or full cancellation to void the original operation. "
        "The reason is sent to rs.ge as k_type; it does not restrict which lines you may edit.")
    rs_einv_needs_k_type = fields.Boolean(compute='_compute_rs_einv_needs_k_type',
        help="Internal flag — True when at least one source invoice has a live rs.ge record and the operator should pick a correction reason.")
    rs_einv_skip_reason_choice = fields.Selection(RS_SKIP_REASON, string='Skip Reason',
        help="Audit reason for a VAT-neutral credit note that should not be filed on rs.ge.")
    rs_einv_flow_preview = fields.Char(string='RS Result', compute='_compute_rs_einv_flow_preview')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'rs_einv_flow' not in fields_list:
            return vals
        active_ids = self.env.context.get('active_ids', [])
        if not active_ids or self.env.context.get('active_model') != 'account.move':
            return vals
        moves = self.env['account.move'].browse(active_ids)
        live_rs = moves.filtered(lambda m: m.rs_einv_id and not m.rs_einv_skip)
        if len(live_rs) == 1 and live_rs.move_type == 'out_invoice':
            vals['rs_einv_flow'] = 'correct_reissue'
        elif live_rs:
            vals['rs_einv_flow'] = 'skip'
        return vals

    @api.depends('move_ids')
    def _compute_rs_einv_needs_k_type(self):
        for record in self:
            record.rs_einv_needs_k_type = any(m.rs_einv_id and not m.rs_einv_skip for m in record.move_ids)

    @api.depends('rs_einv_flow', 'rs_einv_k_type', 'rs_einv_skip_reason_choice')
    def _compute_rs_einv_flow_preview(self):
        k_type_label = dict(RS_K_TYPE_WIZARD)
        skip_label = dict(RS_SKIP_REASON)
        for record in self:
            if record.rs_einv_flow == 'replace':
                record.rs_einv_flow_preview = _("Click 'Reverse and Create Invoice': Odoo will send a cancellation request for the old RS invoice, "
                    "then open a new draft invoice. The buyer approves the cancellation first, then approves the new invoice.")
            elif record.rs_einv_flow == 'correct_reissue':
                label = k_type_label.get(record.rs_einv_k_type)
                if label:
                    record.rs_einv_flow_preview = _("Click 'Reverse and Create Invoice': Odoo opens a corrected new invoice. The original stays "
                        "active until the buyer accepts; rs.ge receives the new invoice as the corrected version of the old one (Reason: %s). Once "
                        "the buyer accepts, the original is cancelled automatically. Buyer approves once.", label)
                else:
                    record.rs_einv_flow_preview = _("Click 'Reverse and Create Invoice': Odoo opens a corrected new invoice. The original stays "
                        "active until the buyer accepts; rs.ge receives the new invoice as the corrected version of the old one. Pick a reason "
                        "above. Once the buyer accepts, the original is cancelled automatically. Buyer approves once.")
            elif record.rs_einv_flow == 'skip':
                reason = skip_label.get(record.rs_einv_skip_reason_choice)
                record.rs_einv_flow_preview = _("Click 'Reverse': rs.ge will receive no filing. Odoo credit note only%s.",
                    reason and _(": %s", reason) or "")
            else:
                record.rs_einv_flow_preview = _("Pick an RS Treatment above to see the expected result.")

    def _prepare_default_reversal(self, move):
        vals = super()._prepare_default_reversal(move)
        if self.rs_einv_flow == 'skip':
            vals.update({'rs_einv_skip': True, 'rs_einv_skip_reason': self.rs_einv_skip_reason_choice})
        return vals

    _RS_REISSUE_FLOWS = ('replace', 'correct_reissue')

    def refund_moves(self):
        """Refreshes rs.ge status once per move first; network errors swallowed, config UserError re-raised."""
        rs_moves = self.move_ids.filtered(lambda m: m.rs_einv_id and not m.rs_einv_skip)
        if not rs_moves:
            return super().refund_moves()

        if self.rs_einv_flow in self._RS_REISSUE_FLOWS:
            label = dict(self._fields['rs_einv_flow'].selection).get(self.rs_einv_flow, self.rs_einv_flow)
            raise UserError(_("The selected RS Treatment ('%s') creates BOTH a credit note and a new replacement invoice. Click 'Reverse and Create "
                "Invoice' instead of 'Reverse' so Odoo can open the new invoice for you to edit.", label))

        replaced_moves = self.move_ids.filtered(lambda m: m.rs_einv_replaced_by_id)
        if replaced_moves:
            move = replaced_moves[0]
            replacement = move.rs_einv_replaced_by_id
            raise UserError(_(
                "Cannot create a credit note on %(old)s because it already "
                "has a replacement flow linked to it:\n"
                "  • Replacement: %(new)s\n"
                "  • Mode: %(mode)s\n\n"
                "Open the replacement invoice and continue from there. A new "
                "credit note on the old invoice would duplicate the local "
                "accounting reversal.",
                old=move.display_name or move.name or '—',
                new=replacement.display_name or replacement.name or '—',
                mode=dict(replacement._fields['rs_einv_replacement_mode'].selection).get(
                    replacement.rs_einv_replacement_mode,
                    replacement.rs_einv_replacement_mode or '—',
                ),
            ))

        if self.rs_einv_flow == 'skip' and not self.rs_einv_skip_reason_choice:
            raise UserError(_("Pick a Skip Reason. A VAT-neutral local credit note needs "
                "an audit reason explaining why no rs.ge correction is filed."))

        if self.rs_einv_flow != 'skip':
            for move in self.move_ids:
                move._rs_safe_refresh_status()
                move._rs_assert_can_be_reversed()
        return super().refund_moves()

    def modify_moves(self):
        rs_moves = self.move_ids.filtered(lambda m: m.rs_einv_id and not m.rs_einv_skip)
        if not rs_moves:
            return super().modify_moves()

        if self.rs_einv_flow not in self._RS_REISSUE_FLOWS:
            label = dict(self._fields['rs_einv_flow'].selection).get(self.rs_einv_flow, self.rs_einv_flow)
            raise UserError(_("The selected RS Treatment ('%s') only creates a credit note — it would discard the new invoice this button is "
                "supposed to open. Click 'Reverse' instead, or change RS Treatment to 'Cancel old RS invoice and issue a new one' or 'Replace RS "
                "invoice with a corrected invoice'.", label))

        if len(rs_moves) != 1 or len(self.move_ids) != 1:
            raise UserError(_("Reverse and Create Invoice can only replace one rs.ge invoice at a time."))
        move = rs_moves[0]
        if move.move_type != 'out_invoice':
            raise UserError(_("Reverse and Create Invoice is not available for supplier-side rs.ge documents. For supplier corrections, use Import "
                "Supplier Correction."))

        if self.rs_einv_flow == 'correct_reissue':
            if not self.rs_einv_k_type:
                raise UserError(_("Pick a Reason for RS correction."))
            return move._rs_do_correct_reissue(k_type=self.rs_einv_k_type)
        # 'replace' is a legacy key kept for backward compatibility.
        return move._rs_do_cancel_reissue()
