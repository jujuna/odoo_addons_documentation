from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .account_move import (
    MAX_FUTURE_DAYS,
    MAX_LINE_NAME_LEN,
    MAX_PAST_YEARS,
    RS_CORRECTION_IN_FLIGHT,
    RS_SKIP_REASON,
    _RS_VAT_NEUTRAL_SKIP_REASONS,
    _rs_status_label,
)
from .account_move_sync import RS_STANDARD_TAX_CATEGORY, RS_VAT_CLASS_BY_TAX_CATEGORY


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _rs_validate(self):
        self.ensure_one()
        if self.rs_einv_skip:
            raise UserError(_("Marked 'Skip rs.ge' (reason: %s) — untick it first to send to rs.ge.",
                dict(RS_SKIP_REASON).get(self.rs_einv_skip_reason, '—')))
        if self.rs_einv_is_buyer_side:
            raise UserError(_("This is a vendor document — the supplier files it. Use 'Pull from rs.ge', then Accept or Reject."))
        if self.state != 'posted' and not (self.state == 'draft' and self._rs_is_sale_correction()):
            raise UserError(_("Post the invoice before sending to rs.ge (current state: %s).", self._rs_field_label(self, 'state')))
        company_tin = (self.company_id.vat or '').strip()
        if not company_tin:
            raise UserError(_("Your company has no TIN (VAT number). Set it under Settings > Companies."))
        if not company_tin.isdigit():
            raise UserError(_("Your company TIN must be digits only (got '%s').") % company_tin)
        partner_tin = (self.partner_id.vat or '').strip()
        if not partner_tin:
            raise UserError(_("Partner '%s' has no TIN — set it on the partner.", self.partner_id.display_name or '—'))
        if not partner_tin.isdigit():
            raise UserError(_("Partner '%s' TIN must be digits only (got '%s').", self.partner_id.display_name or '—', partner_tin))
        if company_tin == partner_tin:
            raise UserError(_("Company and partner share the same TIN (%s) — rs.ge forbids self-invoicing.", company_tin))
        company_ccy = self.company_id.currency_id.name or ''
        if company_ccy and company_ccy.upper() != 'GEL':
            raise UserError(_("Company currency is %s — rs.ge accepts only GEL.", company_ccy))
        today = fields.Date.today()
        inv_date = self.invoice_date
        if inv_date:
            if inv_date > today + timedelta(days=MAX_FUTURE_DAYS):
                raise UserError(_("Invoice date %s is more than %d days ahead — that VAT period does not exist yet.") % (inv_date, MAX_FUTURE_DAYS))
            min_date = fields.Date.subtract(today, years=MAX_PAST_YEARS)
            if inv_date < min_date:
                raise UserError(_("Invoice date %s is over %d years old — that VAT period is closed.") % (inv_date, MAX_PAST_YEARS))
        if (self.move_type in ('out_refund', 'in_refund')
                and self.reversed_entry_id
                and inv_date
                and self.reversed_entry_id.invoice_date
                and inv_date < self.reversed_entry_id.invoice_date):
            raise UserError(_("Credit note date %s is before the "
                "original (%s) — use today or later.") % (inv_date, self.reversed_entry_id.invoice_date))
        product_lines = self._rs_product_lines()
        if not product_lines:
            raise UserError(_("No product lines — add at least one before sending to rs.ge."))
        if self.move_type in ('out_invoice', 'in_invoice'):
            neg_lines = product_lines.filtered(lambda l: l.quantity < -0.0001)
            allowed_dp_offsets = self.env['account.move.line']
            if self.move_type == 'out_invoice' and self._rs_has_downpayment_offset_lines():
                allowed_dp_offsets = neg_lines.filtered(lambda l: getattr(l, 'is_downpayment', False) and (l.price_total or 0.0) < -0.01)
            blocked_neg_lines = neg_lines - allowed_dp_offsets
            if blocked_neg_lines:
                raise UserError(_("%d line(s) have negative quantities — rs.ge "
                    "rejects these on a regular invoice. Use a credit note.") % len(blocked_neg_lines))
        if self._rs_uses_native_advance_attach():
            self._rs_check_native_advance_eligibility(inv_date or today)
        elif self.rs_einv_advance_settlement_mode == 'native_attach' and self.rs_einv_advance_settlement_ids.filtered(lambda s: s.rs_status == '200'):
            raise UserError(_("Native advance settlement needs both delivery lines and down-payment offset lines."))
        empty_name_lines = product_lines.filtered(lambda l: not (l.rs_einv_goods or '').strip())
        if empty_name_lines:
            raise UserError(_("%d line(s) have no product or description — rs.ge requires a name on every line.", len(empty_name_lines)))
        long_name_lines = product_lines.filtered(lambda l: len(l.rs_einv_goods or '') > MAX_LINE_NAME_LEN)
        if long_name_lines:
            raise UserError(_("%d line(s) exceed %d characters — rs.ge would "
                "truncate them. Shorten the product names or labels.") % (len(long_name_lines), MAX_LINE_NAME_LEN))
        if (self.currency_id and self.company_currency_id and self.currency_id != self.company_currency_id):
            rate_date = inv_date or today
            rate = self._rs_get_fx_rate(rate_date)
            if not rate or not rate.rate:
                raise UserError(_("No %s exchange rate on or before %s. Add one "
                    "under Accounting > Configuration > Currencies.") % (self.currency_id.name, rate_date))
        bad_taxes = product_lines.mapped('tax_ids').filtered(lambda t: t.amount < 0)
        if bad_taxes:
            raise UserError(_("Negative-rate tax not supported by rs.ge: %s.") % ', '.join(bad_taxes.mapped('name')))
        if not self.env['account.tax'].search_count([
            *self.env['account.tax']._check_company_domain(self.company_id),
            ('type_tax_use', '=', 'sale'),
            ('ubl_cii_tax_category_code', '=', RS_STANDARD_TAX_CATEGORY),
        ], limit=1):
            raise UserError(_("No sales tax has Tax Category Code S (standard rate), so rs.ge would receive every line without VAT. Set the Tax "
                "Category Code on the VAT taxes in Accounting > Configuration > Taxes."))
        unknown_class_taxes = product_lines.tax_ids.flatten_taxes_hierarchy().filtered_domain([
            ('amount_type', 'in', ('percent', 'division')),
            ('amount', '>', 0),
            ('ubl_cii_tax_category_code', 'not in', list(RS_VAT_CLASS_BY_TAX_CATEGORY)),
        ])
        if unknown_class_taxes:
            raise UserError(_("Tax %s has no Tax Category Code that rs.ge knows, so its lines would be sent without VAT. Set S for VAT, or O if it "
                "is not VAT, in Accounting > Configuration > Taxes.", ', '.join(unknown_class_taxes.mapped('name'))))

    @api.constrains('rs_einv_id')
    def _check_rs_einv_id_format(self):
        for move in self:
            if not move.rs_einv_id:
                continue
            raw = str(move.rs_einv_id).strip()
            if not raw.isdigit() or int(raw) <= 0:
                raise ValidationError(_("RS Invoice ID '%s' must be a positive integer (digits only).", move.rs_einv_id))

    @api.constrains('rs_einv_skip', 'rs_einv_id')
    def _check_rs_skip_consistency(self):
        for move in self:
            if move.rs_einv_skip and move.rs_einv_id:
                raise ValidationError(_("Already on rs.ge (ID %s) — Cancel or Delete on RS before marking Skip.", move.rs_einv_id))

    @api.constrains('rs_einv_skip', 'rs_einv_skip_reason', 'invoice_line_ids', 'state')
    def _check_rs_skip_vat_neutral_lines(self):
        for move in self:
            if (move.state != 'posted'
                    or move.move_type not in ('out_refund', 'in_refund')
                    or not move.rs_einv_skip
                    or move.rs_einv_skip_reason not in _RS_VAT_NEUTRAL_SKIP_REASONS):
                continue
            for line in move._rs_product_lines():
                if line.tax_ids:
                    raise ValidationError(_("Skip reason '%(reason)s' is an expense, not a VAT reversal — line '%(name)s' must carry no tax (has "
                        "%(n)d). Remove the tax.", reason=move.rs_einv_skip_reason, name=line.name or '—', n=len(line.tax_ids)))
                if (line.account_id.account_type or '').startswith('income'):
                    raise ValidationError(_("Skip reason '%(reason)s' is an expense — line '%(name)s' must use an expense account, not income "
                        "'%(account)s'.", reason=move.rs_einv_skip_reason, name=line.name or '—', account=line.account_id.display_name))

    @api.constrains('reversed_entry_id', 'rs_einv_replaces_id', 'rs_einv_replacement_mode', 'rs_einv_status', 'rs_einv_id')
    def _check_unique_pending_correction(self):
        """Drafts are blocked upstream, so this fires only once a correction is on rs.ge."""
        for move in self:
            original = move._rs_chain_parent()
            if (not original or move.rs_einv_status not in RS_CORRECTION_IN_FLIGHT or not move.rs_einv_id):
                continue
            siblings = self.search([
                ('id', '!=', move.id),
                ('rs_einv_status', 'in', list(RS_CORRECTION_IN_FLIGHT)),
                ('rs_einv_id', '!=', False),
                ('rs_einv_replaces_id', '=', original.id),
                ('rs_einv_replacement_mode', '=', 'correction'),
            ])
            if siblings:
                raise ValidationError(_("Another correction is already pending on rs.ge for this invoice: %s (ID %s, status %s). Finish or Delete it "
                    "on RS first.", siblings[0].display_name or '—', siblings[0].rs_einv_id or '—', _rs_status_label(siblings[0].rs_einv_status)))

    @api.onchange('rs_einv_skip')
    def _onchange_rs_einv_skip(self):
        previous_reason = self.rs_einv_skip_reason
        if not self.rs_einv_skip:
            self.rs_einv_skip_reason = False
            if (previous_reason in _RS_VAT_NEUTRAL_SKIP_REASONS and self.move_type in ('out_refund', 'in_refund')):
                has_taxed_line = any(line.tax_ids for line in self.invoice_line_ids if line.display_type == 'product')
                if not has_taxed_line:
                    return {
                        'warning': {
                            'title': _("Un-skip on a VAT-neutral credit note"),
                            'message': _("Tagged '%s' (no taxes) — filing on rs.ge won't reduce VAT. Add taxes first, or keep Skip ticked.",
                                previous_reason),
                        },
                    }

    @api.onchange('rs_einv_note')
    def _onchange_rs_einv_note_length(self):
        """Warn before Odoo's size=255 truncation silently cuts the note (rs.ge stores up to 255 chars)."""
        if self.rs_einv_note and len(self.rs_einv_note) >= 250:
            return {
                'warning': {
                    'title': _("RS Note is nearly at the maximum length"),
                    'message': _("RS Note is %d / 255 characters — anything over 255 is dropped.", len(self.rs_einv_note)),
                },
            }

