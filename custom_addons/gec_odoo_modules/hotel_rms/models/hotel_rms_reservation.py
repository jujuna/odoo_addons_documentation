from odoo import api, fields, models


class HotelRmsReservation(models.Model):
    _name = 'hotel.rms.reservation'
    _description = "Reservation"
    _order = 'arrival desc, id desc'
    _rec_name = 'source_ref'
    _check_company_auto = True

    _source_ref_unique = models.Constraint('UNIQUE(property_id, source_ref)', "A reservation reference can exist only once per hotel.")

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel of this booking.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source_ref = fields.Char(string="Reference", copy=False, index=True,
                             help="The booking number in your reservation system. A booking is updated by its reference.")
    booking_date = fields.Date(string="Booked On", required=True, default=fields.Date.context_today, help="The day the guest booked.")
    arrival = fields.Date(required=True, help="The first night of the stay.")
    departure = fields.Date(required=True, help="The day the guest leaves: the last night is the day before.")
    nights = fields.Integer(compute='_compute_nights', store=True, help="Number of nights of the stay.")
    room_type_id = fields.Many2one('hotel.rms.room.type', string="Room Type", check_company=True, ondelete='restrict',
        domain="[('property_id', '=', property_id)]", help="The room type that was booked.")
    rooms = fields.Integer(default=1, help="How many rooms of this type were booked.")
    revenue = fields.Monetary(currency_field='currency_id',
        help="Room revenue of the whole stay, on the same basis as your prices (with or without tax).")
    status = fields.Selection([('confirmed', "Confirmed"), ('cancelled', "Cancelled"), ('no_show', "No-show")], default='confirmed', required=True,
        help="A cancelled booking counts as booked until its cancellation date; a no-show counts as booked.")
    cancel_date = fields.Date(string="Cancelled On", help="The day the booking was cancelled.")
    channel = fields.Char(help="Where the booking came from, for example Booking.com or Direct.")

    @api.depends('arrival', 'departure')
    def _compute_nights(self):
        for res in self:
            res.nights = (res.departure - res.arrival).days if res.arrival and res.departure else 0
