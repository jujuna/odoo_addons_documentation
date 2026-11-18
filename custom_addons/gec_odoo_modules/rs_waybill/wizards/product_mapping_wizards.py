from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProductMappingWizards(models.TransientModel):
    _name = 'rs.waybill.mapping.wizard'
    _description = 'Resolve unresolved waybill goods'


    waybill_id = fields.Many2one('rs.waybill', required=True, ondelete='cascade')
    line_ids = fields.One2many('rs.waybill.mapping.wizard.line', 'wizard_id')


    def action_apply(self):
        """ Write the chosen product_id back to each real line """

        self.ensure_one()
        missing = self.line_ids.filtered(lambda line: not line.product_id)
        if missing:
            raise UserError(_("Pick a product for every row before applying "
                              "(%d still unmapped).") % len(missing))
        company = self.waybill_id.company_id
        foreign = self.line_ids.product_id.filtered(lambda p: p.company_id and p.company_id != company)
        if company and foreign:
            # The purchase order and receipt are built in the waybill's company: another company's product fails there.
            raise UserError(_("%(products)s belong to another company. Pick products of %(company)s or "
                              "products shared by all companies.")
                            % {'products': ', '.join(foreign.mapped('display_name')), 'company': company.name})

        for wline in self.line_ids:
            # One write: the unit picked here wins over the one guessed from RS.GE's code.
            vals = {'product_id': wline.product_id.id}
            if wline.uom_id:
                vals['uom_id'] = wline.uom_id.id
            wline.line_id.write(vals)

        self.waybill_id._rs_documents_after_mapping()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rs.waybill',
            'res_id': self.waybill_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class MappingWizardLine(models.TransientModel):
    _name = 'rs.waybill.mapping.wizard.line'
    _description = 'One unresolved goods line in the mapping wizard'


    wizard_id = fields.Many2one('rs.waybill.mapping.wizard', required=True, ondelete='cascade')
    line_id = fields.Many2one('rs.waybill.line', required=True, readonly=True)
    external_barcode = fields.Char(readonly=True)
    external_name = fields.Char(readonly=True)
    company_id = fields.Many2one(related='wizard_id.waybill_id.company_id')
    # The waybill's company or shared: the purchase order and receipt are made in that company.
    product_id = fields.Many2one('product.product', domain="[('company_id', 'in', [company_id, False])]")
    rs_unit_name = fields.Char(related='line_id.unit_name', string="Seller's Unit")
    rs_quantity = fields.Float(related='line_id.quantity', string='Quantity')
    allowed_uom_ids = fields.Many2many('uom.uom', compute='_compute_allowed_uom_ids')
    uom_id = fields.Many2one('uom.uom', string='Our Unit', domain="[('id', 'in', allowed_uom_ids)]",
                             help="Which of the product's units the seller's unit is: 2 შეკვრა -> 2 x Pack of 12.")


    @api.depends('product_id')
    def _compute_allowed_uom_ids(self):
        for wline in self:
            wline.allowed_uom_ids = wline.product_id.uom_id | wline.product_id.uom_ids


    @api.onchange('product_id')
    def _onchange_product_id(self):
        line = self.line_id
        self.uom_id = line._rs_match_uom(self.product_id, line.rs_unit_code, line.unit_name)[0]
