from odoo import models, fields, api


class RsWaybillLine(models.Model):
    _name = 'rs.waybill.line'
    _description = 'RS Waybill Line'
    _order = 'rs_waybill_id, sequence, id'


    rs_waybill_id = fields.Many2one('rs.waybill', required=True, ondelete='cascade', index=True)
    rs_good_id = fields.Char(string='RS.GE Good ID', index=True, copy=False,
                             help='ID returned by RS save_waybill in GOODS_LIST. Used for line-level edit/remove.')
    stock_move_id = fields.Many2one('stock.move', string='Source Stock Move', index=True, ondelete='set null', copy=False,
                                    help='The stock move this waybill line was built from. Used to sync quantities.')
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Order Line', index='btree_not_null',
                                       ondelete='set null', copy=False,
                                       help='Vendor waybill: the line of the purchase order made from this waybill.')
    rs_line_status = fields.Selection([('keep', 'Keep'), ('remove', 'Pending removal')], string='RS Line Status',
                                      default='keep', copy=False,
                                      help="'remove' = next save sends STATUS=-1 tombstone to RS; line is deleted after successful save.",)
    sequence = fields.Integer(default=10)

    product_id = fields.Many2one('product.product', string='Product')
    name = fields.Char(string='Name')
    bar_code = fields.Char(string='Code')
    unit_name = fields.Char(string='Unit Name')
    # The line's own unit: quantity and unit_price are per this unit (Pack of 12), not per the product's unit.
    uom_id = fields.Many2one('uom.uom', string='Unit')
    allowed_uom_ids = fields.Many2many('uom.uom', compute='_compute_allowed_uom_ids')
    rs_unit_code = fields.Integer(string='RS Unit Code', readonly=True, copy=False,
                                  help='UNIT_ID this line has on RS.GE (0: not known yet).')
    uom_review = fields.Boolean(string='Unit Needs Review', copy=False,
                                help="RS.GE's unit matches none or several of the product's units: pick the unit "
                                     "before Receive, or the goods would be booked in the wrong unit.")
    quantity = fields.Float(string='Quantity', default=1.0)
    extra_quantity = fields.Float(string='Extra Quantity')
    unit_price = fields.Float(string='Unit Price')
    amount = fields.Float(string='Total', compute='_compute_amount', store=True)
    remainder_quantity = fields.Float(string='Remaining Quantity')
    remainder_amount = fields.Float(string='Remaining Amount')
    parent_remaining = fields.Float(string='Available From Parent', readonly=True)
    vat_type = fields.Selection([('0', 'Standard'), ('1', 'Zero'), ('2', 'Exempt')],default='0', )
    external_barcode = fields.Char(string="Seller's Barcode", readonly=True, help='Barcode as received from RS.GE seller. Preserved for mapping.')
    external_name = fields.Char(string="Seller's Name", readonly=True, help='Product name as received from RS.GE seller. Preserved for mapping.')
    unresolved = fields.Boolean(string='Needs Mapping', default=False, index=True,
                                help='True when this line came from a synced buyer waybill but '
                                      'no internal product matched. User must pick a product.',)
    is_excise_line = fields.Boolean(
        string='Excise',
        related='product_id.is_excise',
        store=True,
        help='True if this line\'s product is marked as excise (used to split the goods view).',
    )


    @api.depends('product_id')
    def _compute_allowed_uom_ids(self):
        for line in self:
            line.allowed_uom_ids = line.product_id.uom_id | line.product_id.uom_ids


    @api.depends('unit_price', 'quantity')
    def _compute_amount(self):
        for line in self:
            line.amount = (line.quantity or 0.0) * (line.unit_price or 0.0)


    @api.onchange('quantity')
    def _onchange_quantity_remainder(self):
        if self.parent_remaining:
            self.remainder_quantity = self.parent_remaining - (self.quantity or 0.0)
        elif self.rs_waybill_id.waybill_type == '4' and not self.rs_waybill_id.parent_waybill_id:
            self.remainder_quantity = self.quantity or 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and not self.external_barcode:
            self.name = self.product_id.name
            # Excise products use RS.GE's "ა{rs_id}" goods code (e.g. ა207); others barcode/default_code.
            tmpl = self.product_id.product_tmpl_id
            if tmpl.is_excise and tmpl.rs_excise_id:
                self.bar_code = f"ა{tmpl.rs_excise_id.rs_id}"
            else:
                self.bar_code = self.product_id.default_code or self.product_id.barcode
            self.unit_price = self.product_id.lst_price
            self.uom_id = self.product_id.uom_id
            self.unit_name = self.product_id.uom_id._rs_text()

    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        if self.uom_id and self.rs_waybill_id.waybill_direction != 'buyer':
            self.unit_name = self.uom_id._rs_text()


    def _rs_unit(self):
        """ The unit quantity and price are in: the line's, else the product's. """
        self.ensure_one()
        return self.uom_id or self.product_id.uom_id


    def _rs_send_unit(self):
        """ (UNIT_ID, UNIT_TXT) sent to RS.GE for this line. """
        self.ensure_one()
        unit = self._rs_unit()
        if unit:
            return unit._rs_code(), unit._rs_text()
        return self.rs_unit_code or 99, self.unit_name or ''


    def _rs_base_qty(self, qty=None):
        """ The line quantity (or qty, in the line's unit) in the product's unit: 2 x Pack of 12 -> 24. """
        self.ensure_one()
        qty = self.quantity if qty is None else qty
        unit, base = self._rs_unit(), self.product_id.uom_id
        if not unit or not base or unit == base:
            return qty
        return unit._compute_quantity(qty, base, round=False)


    def _rs_base_price(self):
        """ The unit price per the product's unit: 30 per Pack of 12 -> 2.50. """
        self.ensure_one()
        unit, base = self._rs_unit(), self.product_id.uom_id
        if not unit or not base or unit == base:
            return self.unit_price
        return unit._compute_price(self.unit_price, base)


    @api.model
    def _rs_match_uom(self, product, rs_code, rs_text):
        """ (uom, needs_review) for a product RS.GE declares in unit rs_code/rs_text: among the product's own units
            (its unit and Packagings) the one with that code, a tie broken by name. None or a tie: the product's unit,
            flagged. No code known: the product's unit, unflagged (nothing to compare). """
        if not product:
            return self.env['uom.uom'], False
        base = product.uom_id
        if not rs_code:
            return base, False
        units = base | product.uom_ids
        matches = units.filtered(lambda u: u._rs_code() == rs_code)
        if len(matches) > 1:
            matches = matches.filtered(lambda u: u.name == rs_text) or matches
        if len(matches) == 1:
            return matches, False
        return base, True


    def write(self, vals):
        """ Capture lines being resolved; a unit picked by hand settles its review. """

        resolving = self.env['rs.waybill.line']
        if vals.get('product_id'):
            resolving = self.filtered(lambda line: not line.product_id and line.external_barcode)
        if vals.get('uom_id') and 'uom_review' not in vals:
            vals = dict(vals, uom_review=False)
        reviewed = self.filtered('uom_review') if vals.get('uom_id') else self.env['rs.waybill.line']

        result = super().write(vals)

        for line in resolving:
            line._save_external_ref()
        if resolving:
            resolving.write({'unresolved': False})
            # The product is known now: so is which of its units RS.GE means.
            for line in resolving.filtered(lambda l: 'uom_id' not in vals and l.rs_unit_code):
                uom, review = line._rs_match_uom(line.product_id, line.rs_unit_code, line.unit_name)
                line.write({'uom_id': uom.id, 'uom_review': review})
        for line in reviewed.filtered(lambda l: l.external_barcode and l.product_id) - resolving:
            line._save_external_ref()
        for waybill in reviewed.rs_waybill_id.filtered(lambda w: not any(w.line_ids.mapped('uom_review'))):
            waybill._rs_documents_after_mapping()

        return result


    def _save_external_ref(self):
        """ Create or update the rs.product.external.ref for this line's seller. """

        self.ensure_one()
        if not (self.product_id and self.external_barcode):
            return
        seller = self.rs_waybill_id._get_seller_partner()
        if not seller:
            return

        ExtRef = self.env['rs.product.external.ref'].sudo()
        template = self.product_id.product_tmpl_id
        wb = self.rs_waybill_id
        # Waybill number, else the RS id (draft buyer waybills have no number).
        origin_wb = wb.rs_waybill_number or (wb.rs_internal_id and 'RS#%s' % wb.rs_internal_id) or ''
        company = wb.company_id or self.env.company
        existing = ExtRef.search([('seller_partner_id', '=', seller.id),
                                  ('external_barcode', '=', self.external_barcode),
                                  ('company_id', '=', company.id)], limit=1)
        # A unit picked for the seller's RS unit code is remembered with the product.
        unit = ({'uom_id': self.uom_id.id, 'rs_unit_code': self.rs_unit_code}
                if self.uom_id and self.rs_unit_code and not self.uom_review else {})
        if existing:
            vals = {
                'product_id': template.id,
                'variant_id': self.product_id.id,
                'external_name': self.external_name or existing.external_name,
                'last_seen_date': fields.Datetime.now(),
                **unit,
            }
            if not existing.origin_waybill_id and not existing.origin_waybill_number:
                vals['origin_waybill_id'] = wb.id
                if origin_wb:
                    vals['origin_waybill_number'] = origin_wb
            existing.write(vals)
        else:
            ExtRef.create({
                'company_id': company.id,
                'product_id': template.id,
                'variant_id': self.product_id.id,
                'seller_partner_id': seller.id,
                'external_barcode': self.external_barcode,
                'external_name': self.external_name,
                'last_seen_date': fields.Datetime.now(),
                'origin_waybill_id': wb.id,
                'origin_waybill_number': origin_wb,
                **unit,
            })


