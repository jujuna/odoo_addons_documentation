from odoo import api, fields, models
from odoo.tools.misc import format_datetime

RUN_STATES = [('done', "Done"), ('stale', "Data too old"), ('busy', "Busy"), ('failed', "Failed")]


class HotelRmsRun(models.Model):
    _name = 'hotel.rms.run'
    _description = "Engine Run"
    _order = 'id desc'
    _check_company_auto = True

    property_id = fields.Many2one('hotel.rms.property', string="Hotel", required=True, ondelete='cascade',
                                  check_company=True, help="The hotel this run was for.")
    company_id = fields.Many2one(related='property_id.company_id', store=True, index=True)
    run_date = fields.Date(string="Run Day", help="Today in the time zone of the hotel when the run started.")
    started_at = fields.Datetime(string="Started", help="When the run started.")
    duration = fields.Float(string="Duration (s)", help="How many seconds the run took.")
    state = fields.Selection(RUN_STATES, default='busy', required=True,
        help="Done: forecasts and prices are fresh. Data too old: nothing changed, import new bookings. Busy: running now, or another run was "
        "already running. Failed: see the message.")
    forecast_version = fields.Char(help="Which forecast rules were used.")
    price_version = fields.Char(help="Which pricing rules were used.")
    params = fields.Json(string="Settings Used", help="The hotel settings, seasons and curves used by this run.")
    params_hash = fields.Char(string="Settings Hash", help="A short code that changes when the settings change.")
    nights = fields.Integer(string="Nights Forecast", help="Number of nights that got a forecast.")
    prices_changed = fields.Integer(string="Prices Changed", help="Number of prices that are new or different.")
    message = fields.Text(help="What to know about this run, for example why it did not change anything.")

    @api.depends('property_id.name', 'started_at')
    def _compute_display_name(self):
        for run in self:
            run.display_name = f"{run.property_id.name} · {format_datetime(self.env, run.started_at)}"
