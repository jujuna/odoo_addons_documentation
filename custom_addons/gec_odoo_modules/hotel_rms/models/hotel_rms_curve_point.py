from odoo import fields, models


class HotelRmsCurvePoint(models.Model):
    _name = 'hotel.rms.curve.point'
    _description = "Curve Point"
    _order = 'property_id, kind, x, id'
    _check_company_auto = True

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this curve belongs to.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    kind = fields.Selection([('demand', "Demand"), ('booking', "Booking")], required=True,
                            help="Demand: price change by occupancy. Booking: share booked by days left.")
    x = fields.Integer(string="From", help="Forecast occupancy % (demand curve) or days left (booking curve).")
    value = fields.Float(string="Value", help="Price change % (demand curve) or % already booked (booking curve).")
    source = fields.Selection([('default', "Default"), ('learned', "Learned")], default='default',
                              help="Learned points were computed from your past bookings.")
