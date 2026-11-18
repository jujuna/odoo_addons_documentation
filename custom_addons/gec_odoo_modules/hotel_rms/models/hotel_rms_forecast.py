from odoo import api, fields, models

from ..engine.forecast import COLDSTART_VERSION, FORECAST_VERSION


class HotelRmsForecast(models.Model):
    _name = 'hotel.rms.forecast'
    _description = "Occupancy Forecast"
    _order = 'run_date desc, stay_date, id'
    _check_company_auto = True

    _night_per_run_unique = models.Constraint('UNIQUE(property_id, run_date, stay_date)', "A night has one forecast per run day.")

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this forecast is for.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    run_date = fields.Date(string="Forecast Made On", required=True, index=True, help="The day the forecast was made.")
    stay_date = fields.Date(string="Night", required=True, index=True, help="The night this forecast is for.")
    lead_days = fields.Integer(string="Days Before", compute='_compute_lead_days', store=True,
                               help="How many days before the night the forecast was made.")
    capacity = fields.Integer(string="Rooms Available", help="Rooms of the hotel that night.")
    otb_rooms = fields.Integer(string="Already Booked", help="Rooms booked for the night when the forecast was made.")
    otb_occ = fields.Float(string="Already Booked %", compute='_compute_otb_occ', store=True, aggregator='avg',
                           help="Share of the rooms already booked.")
    otb_revenue = fields.Monetary(string="Booked Revenue", currency_field='currency_id', help="Room revenue of the booked rooms for this night.")
    expected_otb = fields.Float(string="Usually Booked", help="Rooms usually booked by now for a night like this, from similar past nights.")
    forecast_rooms = fields.Float(string="Forecast Rooms", help="Rooms expected to be booked on the night.")
    forecast_occ = fields.Float(string="Forecast Occupancy %", compute='_compute_forecast_occ', store=True,
                                aggregator='avg', help="Forecast rooms as a share of the rooms available.")
    pace = fields.Float(string="Booking Pace", help="Booked rooms divided by usually booked rooms; 0 when unknown.")
    refs = fields.Integer(string="Comparable Nights", help="Number of similar past nights used for this forecast.")
    method = fields.Selection([(FORECAST_VERSION, "History"), (COLDSTART_VERSION, "Cold start")],
        help="History: from similar past nights. Cold start: from the expected occupancy of the season, while there is no history.")
    confidence_score = fields.Integer(string="Confidence Score", help="0 to 100: how much to trust this forecast.")
    confidence_level = fields.Selection([('low', "Low"), ('medium', "Medium"), ('high', "High")],
                                        string="Confidence", help="How much to trust this forecast.")
    run_id = fields.Many2one('hotel.rms.run', string="Engine Run", ondelete='set null', check_company=True,
                             help="The engine run that made this forecast.")
    is_current = fields.Boolean(string="Current", index=True, default=False, help="Set on the rows of the last finished run.")
    has_actual = fields.Boolean(string="Night Passed", help="The night has passed and its real bookings are known.")
    actual_rooms = fields.Integer(string="Actual Rooms", help="Rooms really booked on the night.")
    error_pts = fields.Float(string="Error (points)", compute='_compute_error_pts', store=True, aggregator='avg',
                             help="How far the forecast was from the real bookings, in points of occupancy.")

    @api.depends('run_date', 'stay_date')
    def _compute_lead_days(self):
        for forecast in self:
            forecast.lead_days = (forecast.stay_date - forecast.run_date).days

    @api.depends('forecast_rooms', 'capacity')
    def _compute_forecast_occ(self):
        for forecast in self:
            forecast.forecast_occ = forecast.forecast_rooms / forecast.capacity * 100 if forecast.capacity else 0

    @api.depends('otb_rooms', 'capacity')
    def _compute_otb_occ(self):
        for forecast in self:
            forecast.otb_occ = forecast.otb_rooms / forecast.capacity * 100 if forecast.capacity else 0

    @api.depends('forecast_rooms', 'actual_rooms', 'capacity', 'has_actual')
    def _compute_error_pts(self):
        for forecast in self:
            forecast.error_pts = (abs(forecast.forecast_rooms - forecast.actual_rooms) / forecast.capacity * 100
                                  if forecast.has_actual and forecast.capacity else 0)
