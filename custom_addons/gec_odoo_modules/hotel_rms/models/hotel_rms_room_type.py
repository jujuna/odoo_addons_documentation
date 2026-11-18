from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRmsRoomType(models.Model):
    _name = 'hotel.rms.room.type'
    _description = "Room Type"
    _order = 'sequence, id'
    _check_company_auto = True

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this room type belongs to.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    name = fields.Char(required=True, help="The name of the room type, for example Double.")
    code = fields.Char(help="A short code. Imports match room types by this code first, then by name.")
    sequence = fields.Integer(default=10, help="Room types are listed in this order.")
    rooms = fields.Integer(string="Rooms", default=1, help="Number of rooms of this type: the capacity of the hotel.")
    active = fields.Boolean(default=True, help="Archive a room type you no longer sell; its prices and bookings stay.")
    derivation = fields.Selection([
        ('reference', "Reference room"),
        ('amount', "Fixed amount above reference"),
        ('percent', "Percent above reference"),
    ], string="Priced as", required=True, default='reference',
        help="The reference room is priced by the engine; the other rooms follow it by an amount or a percent.")
    derive_value = fields.Float(string="Amount / %", help="How much above the reference room: an amount, or a percent of its price.")

    @api.constrains('derivation', 'active', 'property_id')
    def _check_one_reference(self):
        for prop in self.property_id:
            references = prop.room_type_ids.filtered(lambda r: r.derivation == 'reference')
            if len(references) > 1:
                raise ValidationError(self.env._("A hotel has one reference room type only."))

    def _get_caption(self):
        """The line under the room name in the calendar."""
        self.ensure_one()
        if self.derivation == 'amount':
            return self.env._("%s vs reference", f"{self.derive_value:+g}")
        if self.derivation == 'percent':
            return f"{self.derive_value:+g}%"
        return self.env._("Reference room")
