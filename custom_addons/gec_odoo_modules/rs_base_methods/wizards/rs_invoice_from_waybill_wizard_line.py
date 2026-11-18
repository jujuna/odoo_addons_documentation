# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class RsInvoiceFromWaybillWizardLine(models.TransientModel):
    _name = 'rs.invoice.from.waybill.wizard.line'
    _description = 'Create Invoice from Waybill — Line'
    _order = 'waybill_id, id'

    wizard_id = fields.Many2one('rs.invoice.from.waybill.wizard', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='wizard_id.partner_id', store=False)

    waybill_id = fields.Many2one('rs.waybill', required=True)
    waybill_line_id = fields.Many2one('rs.waybill.line', required=True)

    product_id = fields.Many2one('product.product')
    quantity = fields.Float(string='Qty', compute='_compute_quantity', store=True, readonly=False)

    sale_line_id = fields.Many2one('sale.order.line', string='Sale Order Line', compute='_compute_sale_line', store=True, readonly=False)
    sale_order_id = fields.Many2one(related='sale_line_id.order_id', store=False, string='Sale Order')

    unit_price = fields.Float(string='Unit Price', compute='_compute_unit_price', store=True, readonly=False)
    discount = fields.Float(compute='_compute_unit_price', store=True, readonly=False)
    tax_ids = fields.Many2many('account.tax', string='Taxes', compute='_compute_unit_price', store=True, readonly=False)

    qty_to_invoice_remaining = fields.Float(related='sale_line_id.qty_to_invoice', store=False, readonly=True)
    warning = fields.Char(compute='_compute_warning', store=False)

    @api.depends('waybill_line_id', 'partner_id', 'waybill_id.sales_order_id', 'wizard_id.seed_sale_order_id', 'wizard_id.common_sale_order_id')
    def _compute_sale_line(self):
        pool = self._rs_prefetch_sale_line_candidates()
        for line in self:
            line.sale_line_id = line._match_sale_line(candidate_pool=pool)

    def _rs_prefetch_sale_line_candidates(self):
        """Search the sale order lines once for all wizard lines, keyed by (partner_id, product_id)."""
        SOL = self.env['sale.order.line']
        partner_ids, product_ids = set(), set()
        for line in self:
            wb_line = line.waybill_line_id
            if wb_line and wb_line.product_id and line.partner_id:
                partner_ids.add(line.partner_id.id)
                product_ids.add(wb_line.product_id.id)
        if not partner_ids:
            return {}
        candidates = SOL.search([
            ('order_id.partner_id', 'in', list(partner_ids)),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.company_id', '=', self.env.company.id),
            ('product_id', 'in', list(product_ids)),
            ('qty_to_invoice', '>', 0),
            ('display_type', '=', False),
            ('is_downpayment', '=', False),
        ])
        pool = {}
        for cand in candidates:
            key = (cand.order_id.partner_id.id, cand.product_id.id)
            pool[key] = pool.get(key, SOL) | cand
        return pool

    def _match_sale_line(self, candidate_pool=None):
        self.ensure_one()
        wb_line = self.waybill_line_id
        if not wb_line or not wb_line.product_id or not self.partner_id:
            return False
        SOL = self.env['sale.order.line']
        if candidate_pool is None:
            candidates = SOL.search([
                ('order_id.partner_id', '=', self.partner_id.id),
                ('order_id.state', 'in', ('sale', 'done')),
                ('order_id.company_id', '=', self.env.company.id),
                ('product_id', '=', wb_line.product_id.id),
                ('qty_to_invoice', '>', 0),
                ('display_type', '=', False),
                ('is_downpayment', '=', False),
            ])
        else:
            candidates = candidate_pool.get((self.partner_id.id, wb_line.product_id.id), SOL)
        if not candidates:
            return False
        # Prefer the waybill's own or the wizard's seed/common SO, else an unrelated old SO line could match
        preferred_so = self.waybill_id.sales_order_id
        if not preferred_so and self.wizard_id:
            preferred_so = (self.wizard_id.seed_sale_order_id or self.wizard_id.common_sale_order_id)
        narrowed = False
        if preferred_so:
            on_preferred = candidates.filtered(lambda l: l.order_id == preferred_so)
            if on_preferred:
                candidates = on_preferred
                narrowed = True
        if len(candidates) == 1:
            return candidates
        natural = candidates.filtered(lambda l: self.waybill_id in l.order_id.picking_ids.mapped('waybill_id'))
        if len(natural) == 1:
            return natural
        if natural:
            candidates = natural
            narrowed = True
        if narrowed:
            return candidates.sorted('id')[:1]
        return False

    @api.depends('waybill_line_id', 'sale_line_id')
    def _compute_quantity(self):
        """ The waybill quantity in the unit it is invoiced in: the matched SO line's (2 x Pack of 12 declared as
            24 Units invoices 2 packs), else the product's. """
        for line in self:
            wb_line = line.waybill_line_id
            if not wb_line:
                line.quantity = line.quantity or 1.0
                continue
            qty = wb_line._rs_base_qty()
            if line.sale_line_id and wb_line.product_id:
                qty = wb_line.product_id.uom_id._compute_quantity(qty, line.sale_line_id.product_uom_id, round=False)
            line.quantity = qty

    @api.depends('sale_line_id', 'product_id')
    def _compute_unit_price(self):
        for line in self:
            if line.sale_line_id:
                line.unit_price = line.sale_line_id.price_unit
                line.discount = line.sale_line_id.discount
                line.tax_ids = line.sale_line_id.tax_ids
            elif line.product_id:
                line.unit_price = line.product_id.lst_price
                line.discount = 0.0
                wizard = line.wizard_id
                if wizard:
                    line.tax_ids = wizard._product_default_taxes(line.product_id)
                else:
                    line.tax_ids = line.product_id.taxes_id
            else:
                line.unit_price = 0.0
                line.discount = 0.0
                line.tax_ids = [(5, 0, 0)]

    @api.depends('sale_line_id', 'quantity', 'qty_to_invoice_remaining', 'product_id')
    def _compute_warning(self):
        for line in self:
            if not line.product_id:
                line.warning = False
                continue
            if not line.sale_line_id:
                line.warning = _("Unmatched — invoice line will not update qty_invoiced.")
                continue
            if line.quantity > (line.qty_to_invoice_remaining or 0):
                line.warning = _("Quantity %.2f exceeds remaining to invoice %.2f on the SO line.", line.quantity, line.qty_to_invoice_remaining or 0)
                continue
            line.warning = False
