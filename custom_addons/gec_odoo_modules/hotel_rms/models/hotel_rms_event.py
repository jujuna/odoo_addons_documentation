from odoo import api, fields, models


class HotelRmsEvent(models.Model):
    _name = 'hotel.rms.event'
    _description = "Event"
    _order = 'date_from, id'
    _check_company_auto = True

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this event affects.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    name = fields.Char(required=True, help="The name of the event or holiday.")
    date_from = fields.Date(string="From", required=True, help="The first night affected.")
    date_to = fields.Date(string="To", required=True, help="The last night affected.")
    impact_pct = fields.Float(string="Price Impact %",
                              help="Percent added to the price of these nights. The strongest event of a night sets its price.")
    category = fields.Selection([('event', "Event"), ('holiday', "Holiday")], default='event', help="Only changes the colour in the calendar.")
    note = fields.Char(help="Any detail you want to remember about this event.")

    @api.depends('name', 'impact_pct')
    def _compute_display_name(self):
        for event in self:
            event.display_name = f"{event.name} ({event.impact_pct:+g}%)" if event.name else False
