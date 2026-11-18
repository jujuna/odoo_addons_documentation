# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero


class RsInvoiceFromWaybillWizard(models.TransientModel):
    _name = 'rs.invoice.from.waybill.wizard'
    _description = 'Create RS Invoice from Waybills'

    partner_id = fields.Many2one('res.partner', required=True, readonly=True)
    partner_vat = fields.Char(related='partner_id.vat', store=False, readonly=True)
    seed_sale_order_id = fields.Many2one('sale.order', readonly=True)

    waybill_ids = fields.Many2many('rs.waybill', string='Waybills',
        domain="[('waybill_direction','=','seller'), ('is_template','=',False), ('waybill_status','in',('1','2')), ('rs_internal_id','>',0), "
        "('rs_waybill_number','!=',False), ('waybill_type','!=','5'), ('buyer_tin','=', partner_vat), ('is_locked_by_invoice','=', False)]")

    line_ids = fields.One2many('rs.invoice.from.waybill.wizard.line', 'wizard_id', string='Lines')

    invoice_date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one('account.journal', string='Sales Journal', domain="[('type','=','sale'),('company_id','=', company_id)]",
        default=lambda self: self._default_journal())
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, readonly=True)
    note = fields.Text()

    has_unmatched = fields.Boolean(compute='_compute_flags')
    has_overdelivery = fields.Boolean(compute='_compute_flags')
    common_sale_order_id = fields.Many2one('sale.order', string='Sale Order (from waybills)', compute='_compute_common_sale_order', store=False,
        help="Single sale order shared by all selected waybills. When set, it is assigned to the resulting invoice.")
    has_mixed_sale_orders = fields.Boolean(compute='_compute_common_sale_order')
    i_confirm_unmatched = fields.Boolean(string='Confirm: unmatched lines OK')
    i_confirm_overdelivery = fields.Boolean(string='Confirm: over-delivery OK')

    is_standalone = fields.Boolean(default=False, readonly=True,
        help="Set when the wizard is opened from the waybill list view (no seed sale order). Enables line aggregation and skips SO-context preflight "
        "checks.")

    move_type = fields.Selection([('out_invoice', 'Customer Invoice'), ('in_invoice', 'Vendor Bill')], default='out_invoice', required=True,
        readonly=True,
        help="Direction of the resulting accounting document. Today only `out_invoice` is wired through the UI; the field exists so internal helpers "
        "stay direction-agnostic for a future vendor-bill flow.")

    def _is_purchase(self):
        return self.move_type == 'in_invoice'

    def _waybill_direction(self):
        return 'buyer' if self._is_purchase() else 'seller'

    def _waybill_tin_field(self):
        return 'seller_tin' if self._is_purchase() else 'buyer_tin'

    def _journal_type(self):
        return 'purchase' if self._is_purchase() else 'sale'

    def _product_default_taxes(self, product):
        return (product.supplier_taxes_id if self._is_purchase() else product.taxes_id)

    def _resolve_currency(self):
        company_currency = self.env.company.currency_id
        if self._is_purchase():
            return (self.partner_id.property_purchase_currency_id or company_currency)
        pricelist = self.partner_id.property_product_pricelist
        return (pricelist.currency_id if pricelist else False) or company_currency

    def _order_line_model(self):
        return 'purchase.order.line' if self._is_purchase() else 'sale.order.line'

    def _default_journal(self):
        move_type = self.env.context.get('default_move_type') or 'out_invoice'
        jtype = 'purchase' if move_type == 'in_invoice' else 'sale'
        return self.env['account.journal'].search([('type', '=', jtype), ('company_id', '=', self.env.company.id)], limit=1)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if self.env.context.get('default_is_standalone'):
            vals['is_standalone'] = True
        waybill_ids = self.env.context.get('default_waybill_ids')
        if waybill_ids and 'line_ids' in fields_list:
            wb_ids = []
            for cmd in waybill_ids:
                if isinstance(cmd, (list, tuple)) and len(cmd) >= 3 and cmd[0] == 6:
                    wb_ids.extend(cmd[2] or [])
            if wb_ids:
                vals.setdefault('line_ids', self._build_line_commands(wb_ids))
        return vals

    def _build_line_commands(self, waybill_ids):
        commands = []
        waybills = self.env['rs.waybill'].browse(waybill_ids).exists()
        for wb in waybills:
            for wb_line in wb.line_ids:
                if not wb_line.product_id:
                    continue
                commands.append(Command.create({
                    'waybill_id': wb.id,
                    'waybill_line_id': wb_line.id,
                    'product_id': wb_line.product_id.id,
                }))
        return commands

    @api.onchange('waybill_ids')
    def _onchange_waybill_ids(self):
        target_pairs = set()
        for wb in self.waybill_ids:
            for wb_line in wb.line_ids:
                if wb_line.product_id:
                    target_pairs.add((wb.id, wb_line.id))
        snapshot = {}
        current_pairs = set()
        for line in self.line_ids:
            if line.waybill_id and line.waybill_line_id:
                pair = (line.waybill_id.id, line.waybill_line_id.id)
                current_pairs.add(pair)
                snapshot[pair] = {
                    'quantity': line.quantity,
                    'sale_line_id': line.sale_line_id.id if line.sale_line_id else False,
                    'unit_price': line.unit_price,
                    'discount': line.discount,
                    'tax_ids': [Command.set(line.tax_ids.ids)],
                }
        if current_pairs == target_pairs:
            # Keep line_ids seeded by default_get if the onchange fires on form load
            return
        commands = [Command.clear()]
        for wb in self.waybill_ids:
            for wb_line in wb.line_ids:
                if not wb_line.product_id:
                    continue
                vals = {'waybill_id': wb.id, 'waybill_line_id': wb_line.id, 'product_id': wb_line.product_id.id}
                saved = snapshot.get((wb.id, wb_line.id))
                if saved:
                    vals.update(saved)
                commands.append(Command.create(vals))
        self.line_ids = commands

    @api.depends('waybill_ids.sales_order_id')
    def _compute_common_sale_order(self):
        for wiz in self:
            sos = wiz.waybill_ids.mapped('sales_order_id')
            wiz.common_sale_order_id = sos if len(sos) == 1 else False
            wiz.has_mixed_sale_orders = len(sos) > 1

    @api.depends('line_ids.sale_line_id', 'line_ids.quantity', 'line_ids.qty_to_invoice_remaining')
    def _compute_flags(self):
        for wiz in self:
            wiz.has_unmatched = any(not l.sale_line_id and l.product_id for l in wiz.line_ids)
            wiz.has_overdelivery = any(l.sale_line_id and float_compare(l.quantity, l.qty_to_invoice_remaining or 0,
                precision_digits=2) > 0 for l in wiz.line_ids)

    def _validate_preflight(self):
        self.ensure_one()
        if not self.partner_id.vat:
            raise UserError(_("Partner %s has no Tax ID (VAT). Set it before creating the invoice.", self.partner_id.display_name))
        if not self.line_ids:
            raise UserError(_("Nothing to invoice — add at least one waybill."))
        if not self.journal_id:
            raise UserError(_("Pick a sales journal."))
        expected_jtype = self._journal_type()
        if self.journal_id.type != expected_jtype:
            raise UserError(_("Journal %s is not a %s journal.", self.journal_id.display_name, expected_jtype))
        if self.journal_id.company_id != self.env.company:
            raise UserError(_("Journal %s is not in the current company.", self.journal_id.display_name))
        tin_field = self._waybill_tin_field()
        partner_vat = (self.partner_id.vat or '').strip()
        bad_tin = self.waybill_ids.filtered(lambda w: (getattr(w, tin_field) or '').strip() and (getattr(w, tin_field) or '').strip() != partner_vat)
        if bad_tin:
            raise UserError(_("These waybills have a TIN different from the customer: %s",
                ', '.join(bad_tin.mapped('rs_waybill_number') or bad_tin.mapped('display_name'))))
        so_ids = self.waybill_ids.mapped('sales_order_id')
        if len(so_ids) > 1:
            grouped = {}
            for w in self.waybill_ids:
                key = w.sales_order_id.display_name if w.sales_order_id else _("(no SO)")
                grouped.setdefault(key, []).append(w.rs_waybill_number or w.display_name)
            detail = '\n'.join("  %s: %s" % (name, ', '.join(nums)) for name, nums in grouped.items())
            raise UserError(_("Selected waybills are linked to different sale orders. All waybills must share the same sale order (or none):\n%s",
                detail))
        if (self.seed_sale_order_id and so_ids and so_ids != self.seed_sale_order_id):
            raise UserError(_("Selected waybills point to sale order %s, but this wizard was opened from %s.", so_ids.display_name,
                self.seed_sale_order_id.display_name))
        for line in self.line_ids:
            if float_compare(line.quantity, 0, precision_digits=2) <= 0:
                raise UserError(_("Quantity on waybill %s line '%s' must be greater than zero.", line.waybill_id.display_name,
                    line.product_id.display_name))
        lock_date = False
        try:
            lock_date = self.env.company._get_user_fiscal_lock_date(self.journal_id)
        except Exception:
            try:
                lock_date = self.env.company.fiscalyear_lock_date
            except Exception:
                lock_date = False
        if lock_date and self.invoice_date and self.invoice_date <= lock_date:
            raise UserError(_("Invoice date %s is on or before the company fiscal lock date %s.", self.invoice_date, lock_date))
        if (not self.is_standalone and self.has_unmatched and not self.i_confirm_unmatched):
            raise UserError(_("Some waybill lines have no matching sale order line. Tick the confirmation checkbox to proceed."))
        if (not self.is_standalone and self.has_overdelivery and not self.i_confirm_overdelivery):
            raise UserError(_("Some lines invoice more than the remaining quantity. Tick the confirmation checkbox to proceed."))
        if self.is_standalone and not self._aggregate_invoice_lines():
            raise UserError(_("All selected waybill lines net to zero after combining returns with normal deliveries. No invoice will be created."))

    def _prepare_line_vals(self, line):
        """Return the invoice line vals of one wizard line, from
        the matched sale line's _prepare_invoice_line if any."""
        if line.sale_line_id:
            vals = line.sale_line_id._prepare_invoice_line(quantity=line.quantity)
            if not float_is_zero(line.unit_price - line.sale_line_id.price_unit, precision_digits=2):
                vals['price_unit'] = line.unit_price
            if line.discount != line.sale_line_id.discount:
                vals['discount'] = line.discount
            wizard_tax_ids = set(line.tax_ids.ids)
            so_tax_ids = set(line.sale_line_id.tax_ids.ids)
            if wizard_tax_ids != so_tax_ids:
                vals['tax_ids'] = [Command.set(line.tax_ids.ids)]
            if line.waybill_line_id.name and not vals.get('name'):
                vals['name'] = line.waybill_line_id.name
            return vals
        return {
            'product_id': line.product_id.id,
            'name': line.waybill_line_id.name or line.product_id.display_name,
            'quantity': line.quantity,
            'price_unit': line.unit_price,
            'discount': line.discount,
            'product_uom_id': line.product_id.uom_id.id,
            'tax_ids': [Command.set(line.tax_ids.ids)],
        }

    def _aggregate_invoice_lines(self):
        """Return Command.create vals of wizard lines grouped by product, price, discount, uom, taxes and sale line.
        Return waybills (waybill_type '5') count negative and zero-net groups are skipped. Grouping by sale line avoids
        double counting qty_invoiced."""
        grouped = {}
        for line in self.line_ids:
            if not line.product_id:
                continue
            is_return = line.waybill_id.waybill_type == '5'
            qty = -line.quantity if is_return else line.quantity
            sale_line_id = line.sale_line_id.id if line.sale_line_id else False
            key = (
                line.product_id.id,
                float(line.unit_price or 0.0),
                float(line.discount or 0.0),
                # The unit the quantity is in: the matched SO line's, else the product's.
                (line.sale_line_id.product_uom_id or line.product_id.uom_id).id,
                frozenset(line.tax_ids.ids),
                sale_line_id,
            )
            bucket = grouped.setdefault(key, {'quantity': 0.0, 'lines': []})
            bucket['quantity'] += qty
            bucket['lines'].append(line)

        commands = []
        negative_products = []
        for key, bucket in grouped.items():
            qty = bucket['quantity']
            if float_is_zero(qty, precision_digits=2):
                continue
            product_id, unit_price, discount, uom_id, tax_key, sale_line_id = key
            # A negative line cannot be filed on rs.ge: the excess returns need a credit note
            if float_compare(qty, 0.0, precision_digits=2) < 0:
                product = self.env['product.product'].browse(product_id)
                negative_products.append(product.display_name or str(product_id))
                continue
            first_line = bucket['lines'][0]
            vals = {
                'product_id': product_id,
                'name': (first_line.waybill_line_id.name or first_line.product_id.display_name),
                'quantity': qty,
                'price_unit': unit_price,
                'discount': discount,
                'product_uom_id': uom_id,
                'tax_ids': [Command.set(list(tax_key))],
            }
            if sale_line_id:
                vals['sale_line_ids'] = [Command.set([sale_line_id])]
            commands.append(Command.create(vals))
        if negative_products:
            raise UserError(_(
                "These products net to a negative quantity once delivery and "
                "return waybills are combined:\n%(products)s\n\n"
                "A negative line cannot be filed on rs.ge and would desync the "
                "sales order. Issue a credit note for the excess returns "
                "instead of invoicing them here.",
                products="\n".join("• %s" % p for p in negative_products),
            ))
        return commands

    def _prepare_invoice_vals(self):
        self.ensure_one()
        distinct_sos = self.line_ids.mapped('sale_line_id.order_id').sorted('id')
        seed = (
            self.seed_sale_order_id
            or self.common_sale_order_id
            or (False if self.is_standalone
                else (distinct_sos[:1] if distinct_sos else False))
        )
        if seed:
            vals = seed._prepare_invoice()
        else:
            currency = self._resolve_currency()
            vals = {'move_type': self.move_type, 'partner_id': self.partner_id.id, 'company_id': self.env.company.id, 'currency_id': currency.id}
        if not self.is_standalone and distinct_sos and len(distinct_sos) > 1:
            origins = list(dict.fromkeys(distinct_sos.mapped('name')))
            vals['invoice_origin'] = ', '.join(origins)
        vals['invoice_date'] = self.invoice_date
        vals['journal_id'] = self.journal_id.id
        existing_narration = vals.get('narration') or ''
        if self.note:
            vals['narration'] = (existing_narration + '\n' + self.note).strip()
        if self.is_standalone:
            vals['invoice_line_ids'] = self._aggregate_invoice_lines()
        else:
            vals['invoice_line_ids'] = [Command.create(self._prepare_line_vals(line)) for line in self.line_ids]
        vals['rs_einv_waybill_link_ids'] = [Command.create({
            'waybill_id': wb.id,
            'source': 'wizard',
            'sync_state': 'draft',
        }) for wb in self.waybill_ids]
        dp_order = self.common_sale_order_id or self.seed_sale_order_id
        if dp_order:
            dp_commands = self._down_payment_deduction_commands(dp_order)
            if dp_commands:
                vals['invoice_line_ids'] += dp_commands
        return vals

    def _down_payment_deduction_commands(self, order):
        """Return the core down-payment deduction lines (section and negated down payment lines)."""
        dp_lines = order._get_invoiceable_lines(final=True).filtered('is_downpayment')
        if not dp_lines:
            return []
        AccountTax = self.env['account.tax']
        commands = [Command.create(order._prepare_down_payment_section_line())]
        for line in dp_lines:
            reversed_tax_data = AccountTax._reverse_quantity_base_line_extra_tax_data(line.extra_tax_data)
            for line_vals in line._prepare_invoice_lines_vals_list(quantity=-1.0, extra_tax_data=reversed_tax_data):
                commands.append(Command.create(line_vals))
        return commands

    def action_create_invoice(self):
        self.ensure_one()
        self._validate_preflight()
        vals = self._prepare_invoice_vals()
        move = self.env['account.move'].create(vals)
        if move.fiscal_position_id:
            for ml in move.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and not l.is_downpayment):
                mapped = move.fiscal_position_id.map_tax(ml.tax_ids)
                if mapped != ml.tax_ids:
                    ml.tax_ids = [Command.set(mapped.ids)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Invoice'),
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }
