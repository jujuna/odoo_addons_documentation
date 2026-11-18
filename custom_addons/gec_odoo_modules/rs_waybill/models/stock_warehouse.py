from odoo import api, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    rs_distribution_location_id = fields.Many2one(
        'stock.location', string='Distribution Location', copy=False, readonly=True,
        help="Goods on a distribution truck: an activated distribution waybill moves its "
             "goods here, and its sub-waybills deliver from here.")

    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        for warehouse in warehouses:
            warehouse._rs_pickup_type()
        return warehouses

    def _rs_pickup_type(self):
        """ Return the warehouse's "Customer Pickup" Operation Type (waybills "Without Transport",
            RS.GE type 3), creating it if missing. """
        self.ensure_one()
        PickingType = self.env['stock.picking.type'].with_context(active_test=False)
        pickup = PickingType.search([('warehouse_id', '=', self.id), ('code', '=', 'outgoing'),
                                     ('rs_waybill_type', '=', '3')], limit=1)
        if pickup:
            return pickup
        pickup = PickingType.create({
            'name': 'Customer Pickup',
            'code': 'outgoing',
            'sequence_code': 'CP',
            'warehouse_id': self.id,
            'company_id': self.company_id.id,
            'default_location_src_id': self.lot_stock_id.id,
            'default_location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'return_picking_type_id': self.in_type_id.id,
            'rs_create_waybill': True,
            'rs_waybill_type': '3',
        })
        if self.env['res.lang']._lang_get('ka_GE'):
            pickup.with_context(lang='ka_GE').name = 'თვითგატანა'
        return pickup

    def _rs_distribution_location(self):
        """ The warehouse's "Distribution" location: the goods on a distribution truck,
            between the distribution's activation and the sub-waybills' deliveries.
            Created on first use; returned when it exists. """
        self.ensure_one()
        if not self.rs_distribution_location_id:
            self.rs_distribution_location_id = self.env['stock.location'].create({
                'name': 'Distribution',
                'usage': 'internal',
                'location_id': self.view_location_id.id,
                'company_id': self.company_id.id,
            })
        return self.rs_distribution_location_id
