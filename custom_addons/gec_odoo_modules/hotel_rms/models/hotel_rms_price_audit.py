from odoo import api, fields, models


class HotelRmsPriceAudit(models.Model):
    _name = 'hotel.rms.price.audit'
    _description = "Price History"
    _order = 'id desc'
    _check_company_auto = True

    price_id = fields.Many2one('hotel.rms.price', string="Price", required=True, ondelete='cascade',
                               check_company=True, index=True, help="The nightly price this entry is about.")
    property_id = fields.Many2one(related='price_id.property_id', string="Hotel", store=True, index=True)
    company_id = fields.Many2one(related='price_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    stay_date = fields.Date(related='price_id.stay_date', string="Night", store=True)
    room_type_id = fields.Many2one(related='price_id.room_type_id', string="Room Type", store=True)
    action = fields.Selection([
        ('accept', "Accepted"),
        ('edit', "Own price"),
        ('reject', "Rejected"),
        ('undo', "Undone"),
        ('lock', "Locked"),
        ('unlock', "Unlocked"),
        ('import', "Imported"),
        ('export', "Exported"),
        ('apply', "Applied"),
    ], required=True, help="What was done to the price.")
    old_rate = fields.Monetary(string="Old Price", currency_field='currency_id', help="The price before this action.")
    new_rate = fields.Monetary(string="New Price", currency_field='currency_id', help="The price after this action.")
    recommended_rate = fields.Monetary(string="Recommended Price", currency_field='currency_id', help="What the engine recommended at that time.")
    vs_recommended = fields.Float(string="Vs Recommended", compute='_compute_vs_recommended', aggregator='avg',
                                  help="How far the new price is from the recommendation.")
    note = fields.Char(help="The note written with the decision.")
    user_id = fields.Many2one('res.users', string="User", ondelete='set null', help="Who did it.")

    @api.depends('new_rate', 'recommended_rate')
    def _compute_vs_recommended(self):
        for audit in self:
            rate = audit.recommended_rate
            audit.vs_recommended = (audit.new_rate - rate) / rate if rate else 0
