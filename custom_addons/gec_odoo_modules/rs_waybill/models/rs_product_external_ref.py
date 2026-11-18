from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class RsProductExternalRef(models.Model):
    _name = 'rs.product.external.ref'
    _description = 'RS Product External Reference'
    _order = 'product_id, seller_partner_id'


    product_id = fields.Many2one('product.template', string='Our Product', required=True, ondelete='cascade',index=True,)
    variant_id = fields.Many2one(
        'product.product', string='Specific Variant',
        domain="[('product_tmpl_id', '=', product_id)]",
        ondelete='cascade', index=True,
        help='Set only when the template has more than one variant — identifies which specific variant the seller refers to.',
    )
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 default=lambda self: self.env.company)
    seller_partner_id = fields.Many2one('res.partner', string='Seller', required=True, index=True,
                                        help='The partner who uses this external barcode/name for our product.',)
    external_barcode = fields.Char(string="Seller's Barcode", required=True, index=True,)
    external_name = fields.Char(string="Seller's Product Name", help='Last seen name from this seller for this barcode. For human reference only.',)
    # The unit picked in Resolve Now for the seller's RS.GE unit code: the next waybill reuses it instead of asking.
    uom_id = fields.Many2one('uom.uom', string='Our Unit',
                             help="Which of our product's units the seller's unit is (e.g. their შეკვრა = Pack of 24).")
    rs_unit_code = fields.Integer(string="Seller's RS Unit Code",
                                  help='The RS.GE UNIT_ID the seller sent when Our Unit was picked.')
    last_seen_date = fields.Datetime(string='Last Seen', help='Updated each time we resolve a waybill goods line via this mapping.',)
    origin_waybill_id = fields.Many2one('rs.waybill', string='Mapped From Waybill', readonly=True, ondelete='set null',
                                        help="The RS waybill this seller↔product mapping was first created from. "
                                             "Click to open it.")
    origin_waybill_number = fields.Char(string='Mapped From Waybill (No.)', readonly=True,
                                        help="Text copy of the originating waybill number — preserved for tracing even "
                                             "if that waybill is later deleted.")

    _unique_seller_barcode = models.Constraint(
        'UNIQUE(company_id, seller_partner_id, external_barcode)',
        'This seller already has a mapping for this external barcode in this company.',
    )


    @api.constrains('product_id', 'variant_id')
    def _check_variant_required_for_multivariant(self):
        for rec in self:
            if not rec.variant_id and len(rec.product_id.product_variant_ids) > 1:
                raise ValidationError(_("Product %s has multiple variants — pick the specific variant "
                                        "in 'Specific Variant'.") % rec.product_id.display_name)
            # A domain is UI only: an import or ORM write can pair a variant with an unrelated template.
            if rec.variant_id and rec.variant_id.product_tmpl_id != rec.product_id:
                raise ValidationError(_("Variant '%(variant)s' does not belong to product '%(product)s'.") % {
                    'variant': rec.variant_id.display_name,
                    'product': rec.product_id.display_name})


    @api.depends('product_id.display_name', 'seller_partner_id.name', 'external_barcode')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (f"{rec.seller_partner_id.name or '?'}: "
                                f"{rec.external_barcode or '?'} → "
                                f"{rec.product_id.display_name or '?'}")