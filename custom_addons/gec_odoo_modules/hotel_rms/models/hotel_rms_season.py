from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRmsSeason(models.Model):
    _name = 'hotel.rms.season'
    _description = "Season"
    _order = 'date_from, id'
    _check_company_auto = True

    _rates_in_order = models.Constraint('CHECK(min_rate <= base_rate AND base_rate <= max_rate)',
        "The base price must be between the minimum and the maximum price.")

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this season belongs to.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(required=True, help="The name of the season, for example High season.")
    date_from = fields.Date(string="From", required=True, help="The first night of the season.")
    date_to = fields.Date(string="To", required=True, help="The last night of the season.")
    base_rate = fields.Monetary(string="Base Price", currency_field='currency_id',
                                help="The price of the reference room before any change for the weekday, events or demand.")
    min_rate = fields.Monetary(string="Minimum Price", currency_field='currency_id', help="The engine never recommends less than this.")
    max_rate = fields.Monetary(string="Maximum Price", currency_field='currency_id', help="The engine never recommends more than this.")
    expected_occ_pct = fields.Float(string="Expected Occupancy %", help="Used for the forecast while there is no booking history.")

    @api.constrains('property_id', 'date_from', 'date_to')
    def _check_no_overlap(self):
        for season in self:
            if self.search_count([
                ('id', '!=', season.id),
                ('property_id', '=', season.property_id.id),
                ('date_from', '<=', season.date_to),
                ('date_to', '>=', season.date_from),
            ]):
                raise ValidationError(self.env._("Seasons of the same hotel cannot overlap."))

    def action_copy_next_year(self):
        for season in self:
            season.copy({'date_from': season.date_from + relativedelta(years=1), 'date_to': season.date_to + relativedelta(years=1)})
