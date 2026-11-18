import ast
import csv
import hashlib
import io
import json
import logging
import time
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.addons.base.models.res_partner import _tz_get

from ..engine import forecast as forecast_engine
from ..engine import pricing as pricing_engine
from .hotel_rms_run import RUN_STATES

_logger = logging.getLogger(__name__)

DEMAND_CURVE_DEFAULT = ((0, -10), (40, -5), (60, 0), (75, 5), (85, 10), (92, 15))
BOOKING_CURVE_DEFAULT = ((0, 100), (3, 92), (7, 82), (14, 68), (30, 48), (60, 28), (90, 15), (180, 5))
DOW_FIELDS = ('dow_mon', 'dow_tue', 'dow_wed', 'dow_thu', 'dow_fri', 'dow_sat', 'dow_sun')
PARAM_FIELDS = ('horizon_days', 'price_step', 'max_step_pct', 'min_change_pct', 'stale_after_days', 'min_refs', 'ref_window_days', 'ref_years',
    'recent_weeks', 'pace_threshold_pct', 'pace_adj_pct', 'lastmin_days', 'lastmin_occ_pct', 'lastmin_pct', 'protect_days', 'protect_occ_pct',
    *DOW_FIELDS)
ACTUALS_DAYS = 60
KPI_DAYS = 30
MAX_CALENDAR_DAYS = 60
INSIGHT_DAYS = 90
HEATMAP_DAYS = 60
WEEK_DAYS = 7
YEAR_DAYS = 364
ACCURACY_DAYS = 56
ACCURACY_LEADS = (7, 30)
ACCURACY_GOOD_PTS = 5
ACCURACY_FAIR_PTS = 10
LATEST_CHANGES = 10


class HotelRmsProperty(models.Model):
    _name = 'hotel.rms.property'
    _description = "Hotel"
    _inherit = ['mail.thread']
    _order = 'name, id'

    name = fields.Char(required=True, tracking=True, help="The name of the hotel.")
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company,
                                 help="The company that owns this hotel and its prices.")
    currency_id = fields.Many2one(related='company_id.currency_id')
    tz = fields.Selection(_tz_get, string="Time Zone", default=lambda self: self.env.user.tz, help="Defines 'today' and the nights of this hotel.")
    is_demo = fields.Boolean(string="Demo Hotel", readonly=True, copy=False,
                             help="A sample hotel made by Configuration > Demo Data. Remove it with the button on its form.")
    last_data_at = fields.Datetime(string="Data Updated", readonly=True, copy=False, help="When bookings were last imported or read.")
    is_stale = fields.Boolean(compute='_compute_stale')
    data_age_days = fields.Integer(compute='_compute_stale')

    horizon_days = fields.Integer(string="Days Ahead", default=90, help="How many nights ahead the engine forecasts and prices.")
    price_step = fields.Float(string="Price Step", default=1, help="Prices are rounded to a multiple of this value.")
    dow_mon = fields.Float(string="Monday %", help="Percent added to Monday prices (negative lowers them).")
    dow_tue = fields.Float(string="Tuesday %", help="Percent added to Tuesday prices (negative lowers them).")
    dow_wed = fields.Float(string="Wednesday %", help="Percent added to Wednesday prices (negative lowers them).")
    dow_thu = fields.Float(string="Thursday %", help="Percent added to Thursday prices (negative lowers them).")
    dow_fri = fields.Float(string="Friday %", help="Percent added to Friday prices (negative lowers them).")
    dow_sat = fields.Float(string="Saturday %", help="Percent added to Saturday prices (negative lowers them).")
    dow_sun = fields.Float(string="Sunday %", help="Percent added to Sunday prices (negative lowers them).")

    max_step_pct = fields.Float(string="Maximum Change %", default=15,
                                help="A price moves at most this much from the current price (the season range wins).")
    min_change_pct = fields.Float(string="Minimum Change %", default=3, help="Smaller changes keep the current price.")
    protect_days = fields.Integer(string="Protect Within Days", default=7,
                                  help="Within this many days before the night, a nearly full night is protected.")
    protect_occ_pct = fields.Float(string="Protect From Occupancy %", default=85,
                                   help="Close to the night and nearly full: never lower the current price.")
    lastmin_days = fields.Integer(string="Last Minute Within Days", default=3,
                                  help="Within this many days before the night, the last-minute discount can apply.")
    lastmin_occ_pct = fields.Float(string="Last Minute Below Occupancy %", default=60,
                                   help="The discount applies only while the forecast occupancy is below this.")
    lastmin_pct = fields.Float(string="Last Minute %", default=-10, help="Percent added to the price of a last-minute night (negative lowers it).")
    pace_threshold_pct = fields.Float(string="Pace Threshold %", default=10,
                                      help="Bookings must be this far ahead or behind usual before the price reacts.")
    pace_adj_pct = fields.Float(string="Pace Adjustment %", default=5, help="Percent the price moves when bookings are ahead of or behind usual.")
    stale_after_days = fields.Integer(string="Data Stale After Days", default=2,
                                      help="Recommendations are frozen when the booking data is older than this.")
    min_refs = fields.Integer(string="Minimum Comparable Nights", default=3, help="Fewest similar past nights needed to forecast from history.")
    ref_window_days = fields.Integer(string="Comparable Window Days", default=21,
                                     help="How many days around the same date last year count as similar nights.")
    ref_years = fields.Integer(string="Comparable Years", default=2, help="How many past years are searched for similar nights.")
    recent_weeks = fields.Integer(string="Comparable Recent Weeks", default=8, help="How many recent weeks are searched for similar nights.")
    curve_min_nights = fields.Integer(string="Nights Needed To Learn Curve", default=30,
                                      help="Fewest past nights needed before the booking curve can be learned.")

    room_type_ids = fields.One2many('hotel.rms.room.type', 'property_id', string="Room Types")
    season_ids = fields.One2many('hotel.rms.season', 'property_id', string="Seasons")
    demand_point_ids = fields.One2many('hotel.rms.curve.point', 'property_id', string="Demand Curve", domain=[('kind', '=', 'demand')])
    booking_point_ids = fields.One2many('hotel.rms.curve.point', 'property_id', string="Booking Curve", domain=[('kind', '=', 'booking')])
    event_ids = fields.One2many('hotel.rms.event', 'property_id', string="Events")

    setup_rooms = fields.Boolean(compute='_compute_setup')
    setup_season = fields.Boolean(compute='_compute_setup')
    setup_bookings = fields.Boolean(compute='_compute_setup')
    setup_run = fields.Boolean(compute='_compute_setup')
    setup_done = fields.Boolean(compute='_compute_setup')
    pending_count = fields.Integer(compute='_compute_counts')
    reservation_count = fields.Integer(compute='_compute_counts')
    import_count = fields.Integer(compute='_compute_counts')
    run_count = fields.Integer(compute='_compute_counts')
    last_run_state = fields.Selection(RUN_STATES, compute='_compute_counts')
    forecast_occ = fields.Float(string="Forecast Occupancy %", compute='_compute_dashboard', help="Forecast occupancy of the next 30 nights.")
    otb_occ = fields.Float(string="Already Booked %", compute='_compute_dashboard', help="Share of the rooms already booked for the next 30 nights.")
    forecast_series = fields.Json(compute='_compute_dashboard', help="Forecast occupancy of each of the next 30 nights.")
    decision_split = fields.Json(compute='_compute_dashboard', help="Prices accepted, set by you and rejected this month.")

    @api.depends('last_data_at', 'stale_after_days')
    def _compute_stale(self):
        now = fields.Datetime.now()
        for prop in self:
            age = now - prop.last_data_at if prop.last_data_at else None
            prop.data_age_days = age.days if age else 0
            prop.is_stale = age is None or age > timedelta(days=prop.stale_after_days)

    @api.depends('room_type_ids.derivation', 'season_ids.date_from', 'season_ids.date_to', 'last_data_at', 'horizon_days')
    def _compute_setup(self):
        for prop in self:
            today = prop._get_local_today()
            prop.setup_rooms = any(room.derivation == 'reference' for room in prop.room_type_ids)
            prop.setup_season = bool(prop.season_ids) and all(prop._get_season(today + timedelta(days=i)) for i in range(prop.horizon_days))
            prop.setup_bookings = bool(prop.last_data_at)
            prop.setup_run = bool(prop._origin.id) and bool(self.env['hotel.rms.run'].search_count(
                [('property_id', '=', prop._origin.id), ('state', '=', 'done')]))
            prop.setup_done = prop.setup_rooms and prop.setup_season and prop.setup_bookings and prop.setup_run

    def _compute_counts(self):
        for prop in self:
            domain = [('property_id', '=', prop._origin.id)]
            prop.pending_count = self.env['hotel.rms.price'].search_count(domain + [('state', '=', 'pending')])
            prop.reservation_count = self.env['hotel.rms.reservation'].search_count(domain)
            prop.import_count = self.env['hotel.rms.import'].search_count(domain)
            prop.run_count = self.env['hotel.rms.run'].search_count(domain)
            prop.last_run_state = self.env['hotel.rms.run'].search(domain, limit=1).state

    def _compute_dashboard(self):
        """Next KPI_DAYS nights from each hotel's local today, and this month's decisions."""
        Forecast = self.env['hotel.rms.forecast']
        Audit = self.env['hotel.rms.price.audit']
        for tz, hotels in self.grouped('tz').items():
            today = hotels[0]._get_local_today()
            rows = Forecast.search_fetch([
                ('property_id', 'in', hotels._origin.ids),
                ('is_current', '=', True),
                ('stay_date', '>=', today),
                ('stay_date', '<', today + timedelta(days=KPI_DAYS)),
            ], ['property_id', 'otb_rooms', 'forecast_rooms', 'capacity', 'forecast_occ'], order='stay_date')
            decisions = Audit.with_context(tz=tz or 'UTC')._read_group([
                ('property_id', 'in', hotels._origin.ids),
                ('action', 'in', ('accept', 'edit', 'reject')),
                ('create_date', '>=', today.replace(day=1)),
            ], ['property_id', 'action'], ['__count'])
            counts = {(hotel.id, action): count for hotel, action, count in decisions}
            rows_by_hotel = rows.grouped('property_id')
            for hotel in hotels:
                hotel_rows = rows_by_hotel.get(hotel._origin, Forecast)
                capacity = sum(hotel_rows.mapped('capacity'))
                hotel.forecast_occ = sum(hotel_rows.mapped('forecast_rooms')) / capacity * 100 if capacity else 0
                hotel.otb_occ = sum(hotel_rows.mapped('otb_rooms')) / capacity * 100 if capacity else 0
                hotel.forecast_series = hotel_rows.mapped('forecast_occ')
                hotel.decision_split = {
                    'accepted': counts.get((hotel._origin.id, 'accept'), 0),
                    'edited': counts.get((hotel._origin.id, 'edit'), 0),
                    'rejected': counts.get((hotel._origin.id, 'reject'), 0),
                }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('demand_point_ids'):
                vals['demand_point_ids'] = [Command.create({
                    'kind': 'demand',
                    'x': x,
                    'value': value,
                    'source': 'default',
                }) for x, value in DEMAND_CURVE_DEFAULT]
            if not vals.get('booking_point_ids'):
                vals['booking_point_ids'] = [Command.create({
                    'kind': 'booking',
                    'x': x,
                    'value': value,
                    'source': 'default',
                }) for x, value in BOOKING_CURVE_DEFAULT]
        return super().create(vals_list)

    def _get_local_today(self, timestamp=None):
        """Today (or the date of a UTC timestamp) in the hotel time zone: the one 'today' of every engine rule."""
        self.ensure_one()
        return fields.Date.context_today(self.with_context(tz=self.tz or 'UTC'), timestamp)

    def _get_season(self, day):
        self.ensure_one()
        return self.season_ids.filtered(lambda s: s.date_from <= day <= s.date_to)[:1]

    def _sync_sources(self):
        """Hook: bridge modules read bookings and current prices here; nothing in core."""

    def _load_night_index(self, date_from, date_to):
        self.ensure_one()
        reservations = self.env['hotel.rms.reservation'].search_fetch([
            ('property_id', '=', self.id),
            ('departure', '>', date_from),
            ('arrival', '<', date_to),
        ], ['booking_date', 'arrival', 'departure', 'rooms', 'revenue', 'status', 'cancel_date'])
        return forecast_engine.night_index([{
            'booking_date': res.booking_date,
            'arrival': res.arrival,
            'departure': res.departure,
            'rooms': res.rooms,
            'revenue': res.revenue,
            'cancel_date': (res.cancel_date or res.booking_date) if res.status == 'cancelled' else None,
        } for res in reservations])

    def action_run_engine(self):
        for prop in self:
            prop._run_engine()
        return True

    @api.model
    def _cron_run_engine(self):
        """Daily run for every hotel, as the cron user; each hotel is committed on its own."""
        properties = self.search([])
        self.env['ir.cron']._commit_progress(remaining=len(properties))
        for prop in properties:
            prop.with_company(prop.company_id)._run_engine()
            self.env['ir.cron']._commit_progress(1)

    def _run_engine(self):
        """Always leaves one run row; an engine error is logged on it, not raised."""
        self.ensure_one()
        started = time.monotonic()
        today = self._get_local_today()
        locked = self.try_lock_for_update(allow_referencing=True)
        run = self.env['hotel.rms.run'].create({
            'property_id': self.id,
            'run_date': today,
            'started_at': fields.Datetime.now(),
            'state': 'busy',
            'forecast_version': forecast_engine.FORECAST_VERSION,
            'price_version': pricing_engine.PRICE_VERSION,
        })
        if not locked:
            run.message = self.env._("Another run of this hotel is in progress.")
            return run
        try:
            with self.env.cr.savepoint():
                self._sync_sources()
                if self.is_stale:
                    run.write({
                        'state': 'stale',
                        'message': self.env._("The booking data is older than %s days. Import new reservations.", self.stale_after_days),
                    })
                else:
                    nights, changed = self._compute_run(run, today)
                    params = {name: self[name] for name in PARAM_FIELDS}
                    params['seasons'] = [{
                        'name': s.name,
                        'date_from': fields.Date.to_string(s.date_from),
                        'date_to': fields.Date.to_string(s.date_to),
                        'base_rate': s.base_rate,
                        'min_rate': s.min_rate,
                        'max_rate': s.max_rate,
                        'expected_occ_pct': s.expected_occ_pct,
                    } for s in self.season_ids]
                    params['curves'] = [{'kind': p.kind, 'x': p.x, 'value': p.value} for p in self.demand_point_ids + self.booking_point_ids]
                    run.write({
                        'state': 'done',
                        'nights': nights,
                        'prices_changed': changed,
                        'params': params,
                        'params_hash': hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12],
                    })
        except Exception as exc:
            _logger.exception("Revenue engine failed for hotel %s", self.id)
            run.write({'state': 'failed', 'message': self.env._("The engine stopped: %s. See server log.", type(exc).__name__)})
        run.duration = time.monotonic() - started
        return run

    def _compute_run(self, run, today):
        """Returns (nights forecast, prices new or changed)."""
        self.ensure_one()
        rooms = self.room_type_ids
        capacity = sum(rooms.mapped('rooms'))
        if capacity <= 0:
            run.message = self.env._("The hotel has no rooms.")
            return 0, 0
        reference = rooms.filtered(lambda r: r.derivation == 'reference')[:1]
        if not reference:
            run.message = self.env._("No reference room type: forecasts only, no prices.")
        earliest = today - timedelta(days=max(364 * self.ref_years + self.ref_window_days, 7 * (self.recent_weeks + 1), ACTUALS_DAYS))
        index = self._load_night_index(earliest, today + timedelta(days=self.horizon_days))
        results, forecasts = self._compute_forecasts(run, today, index, capacity)
        changed = self._compute_prices(run, today, reference, results, forecasts) if reference else 0
        self._compute_actuals(today, index)
        return len(results), changed

    def _compute_forecasts(self, run, today, index, capacity):
        """One create; returns ({night: result}, {night: forecast row}); nights without a result are left out."""
        Forecast = self.env['hotel.rms.forecast']
        [(history_start,)] = self.env['hotel.rms.reservation']._read_group([('property_id', '=', self.id)], [], ['booking_date:min'])
        booking_curve = sorted((p.x, p.value / 100) for p in self.booking_point_ids)
        results = {}
        vals_by_night = {}
        for lead in range(self.horizon_days):
            night = today + timedelta(days=lead)
            season = self._get_season(night)
            refs = forecast_engine.comparable_dates(night, today, self.ref_window_days, self.ref_years, self.recent_weeks)
            result = forecast_engine.forecast_v1(index, night, today, capacity, refs, self.min_refs, history_start)
            if result is None and season and booking_curve:
                booked, revenue = forecast_engine.otb(index, night, today)
                result = forecast_engine.coldstart_v1(booked, revenue, capacity, season.expected_occ_pct / 100, lead, booking_curve)
            if not result:
                continue
            score, level = forecast_engine.confidence(result['method'], result['refs'], self.data_age_days)
            results[night] = result
            vals_by_night[night] = {
                'capacity': capacity,
                'otb_rooms': result['otb'],
                'otb_revenue': result['otb_revenue'],
                'expected_otb': result['expected_otb'],
                'forecast_rooms': result['forecast_rooms'],
                'pace': result['pace'] or 0,
                'refs': result['refs'],
                'method': result['method'],
                'confidence_score': score,
                'confidence_level': level,
                'run_id': run.id,
                'is_current': True,
            }
        forecasts = {f.stay_date: f for f in Forecast.search_fetch([('property_id', '=', self.id), ('run_date', '=', today)], ['stay_date'])}
        to_create = []
        for night, vals in vals_by_night.items():
            if night in forecasts:
                forecasts[night].write(vals)
            else:
                to_create.append(dict(vals, property_id=self.id, run_date=today, stay_date=night))
        forecasts.update({f.stay_date: f for f in Forecast.create(to_create)})
        Forecast.search([('property_id', '=', self.id), ('is_current', '=', True), ('run_id', '!=', run.id)]).write({'is_current': False})
        return results, forecasts

    def _compute_prices(self, run, today, reference, results, forecasts):
        """Nights without a season are held; returns how many prices are new or changed."""
        Price = self.env['hotel.rms.price']
        rooms = self.room_type_ids
        capacity = sum(rooms.mapped('rooms'))
        horizon_end = today + timedelta(days=self.horizon_days)
        demand_curve = [(p.x, p.value) for p in self.demand_point_ids]
        rules = {name: self[name] for name in PARAM_FIELDS}
        prices = {(p.stay_date, p.room_type_id.id): p for p in Price.search_fetch([
            ('property_id', '=', self.id),
            ('stay_date', '>=', today),
            ('stay_date', '<', horizon_end),
        ], ['property_id', 'stay_date', 'room_type_id', 'published_rate', 'recommended_rate', 'action', 'locked', 'decided_at'])}
        to_create = []
        unpriced = Price
        changed = 0

        for lead in range(self.horizon_days):
            night = today + timedelta(days=lead)
            season = self._get_season(night)
            result = results.get(night)
            if season and not result:
                continue
            if not season:
                for room in rooms:
                    row = prices.get((night, room.id))
                    if row and not row._engine_skip_write(today):
                        unpriced |= row
                continue

            forecast = forecasts[night]
            events = self.event_ids.filtered(lambda e: e.date_from <= night <= e.date_to)
            event = max(events, key=lambda e: abs(e.impact_pct), default=self.env['hotel.rms.event'])
            forecast_occ = result['forecast_rooms'] / capacity * 100
            reference_row = prices.get((night, reference.id))
            reference_result = pricing_engine.price_v1(dict(rules, base=season.base_rate, min_rate=season.min_rate, max_rate=season.max_rate,
                current_rate=reference_row.published_rate if reference_row else 0, dow_pct=rules[DOW_FIELDS[night.weekday()]],
                event_pct=event.impact_pct, forecast_occ=forecast_occ, pace=result['pace'], method=result['method'], lead=lead,
                demand_curve=demand_curve))
            for room in rooms:
                row = prices.get((night, room.id))
                price = reference_result if room == reference else pricing_engine.derive(reference_result, room.derivation, room.derive_value,
                    row.published_rate if row else 0, self.price_step, self.min_change_pct)
                vals = {
                    'forecast_id': forecast.id,
                    'raw_target_rate': price['raw_target'],
                    'recommended_rate': price['recommended'],
                    'action': price['action'],
                    'state': 'hold' if price['action'] == 'hold' else 'pending',
                    'run_id': run.id,
                    'reason_json': {
                        'base': season.base_rate,
                        'season': season.name,
                        'lead': lead,
                        'method': result['method'],
                        'forecast_occ': round(forecast_occ, 1),
                        'pace': result['pace'],
                        'event': event.name or False,
                        'event_pct': event.impact_pct,
                        'derivation': room.derivation,
                        'derive_value': room.derive_value,
                        'factors': price['factors'],
                        'guards': price['guards'],
                        'waterfall': price['waterfall'],
                    },
                }
                if not row:
                    to_create.append(dict(vals, property_id=self.id, stay_date=night, room_type_id=room.id))
                    changed += 1
                elif not row._engine_skip_write(today):
                    if (self.currency_id.compare_amounts(row.recommended_rate, price['recommended']) or row.action != price['action']):
                        changed += 1
                    row.write(vals)
        unpriced.write({
            'recommended_rate': 0,
            'raw_target_rate': 0,
            'action': False,
            'state': 'hold',
            'reason_json': False,
            'run_id': run.id,
        })
        Price.create(to_create)
        return changed

    def _compute_actuals(self, today, index):
        past = self.env['hotel.rms.forecast'].search_fetch([
            ('property_id', '=', self.id),
            ('stay_date', '>=', today - timedelta(days=ACTUALS_DAYS)),
            ('stay_date', '<', today),
        ], ['stay_date', 'has_actual', 'actual_rooms'])
        for stay_date, rows in past.grouped('stay_date').items():
            actual = forecast_engine.otb(index, stay_date, stay_date)[0]
            rows.filtered(lambda r: not r.has_actual or r.actual_rooms != actual).write({'actual_rooms': actual, 'has_actual': True})

    def action_learn_booking_curve(self):
        self.ensure_one()
        today = self._get_local_today()
        index = self._load_night_index(today - timedelta(days=forecast_engine.CURVE_HISTORY_DAYS), today)
        leads = self.booking_point_ids.mapped('x')
        curve = forecast_engine.learn_curve(index, today, leads, self.curve_min_nights)
        if curve is None:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': self.env._("Not enough history: %s nights with bookings are needed.", self.curve_min_nights),
                },
            }
        self.booking_point_ids.unlink()
        self.booking_point_ids = [Command.create({
            'kind': 'booking',
            'x': lead,
            'value': share * 100,
            'source': 'learned',
        }) for lead, share in curve]
        return True

    def action_open_calendar(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('hotel_rms.action_pricing_calendar')
        action['context'] = {'property_id': self.id}
        return action

    def action_open_review(self):
        """Open the prices of this hotel that need a decision."""
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('hotel_rms.action_hotel_rms_price')
        action['context'] = dict(ast.literal_eval(action['context']), search_default_property_id=self.id)
        return action

    def action_publish_approved(self):
        self.ensure_one()
        prices = self.env['hotel.rms.price'].search([('property_id', '=', self.id), ('to_export', '=', True)], order='stay_date, room_type_id')
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['date', 'room_type', 'price'])
        for price in prices:
            writer.writerow([fields.Date.to_string(price.stay_date), price.room_type_id.code or price.room_type_id.name, price.published_rate])
        attachment = self.env['ir.attachment'].create({
            'name': f"approved_prices_{self._get_local_today()}.csv",
            'raw': buffer.getvalue().encode(),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })
        prices._mark_exported('export')
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true'}

    def _get_kpis(self, forecasts):
        """Booked and forecast occupancy, ADR and RevPAR of forecast rows, from period sums."""
        otb_rooms = sum(forecasts.mapped('otb_rooms'))
        forecast_rooms = sum(forecasts.mapped('forecast_rooms'))
        capacity = sum(forecasts.mapped('capacity'))
        otb_revenue = sum(forecasts.mapped('otb_revenue'))
        adr = otb_revenue / otb_rooms if otb_rooms else 0
        forecast_occ = forecast_rooms / capacity * 100 if capacity else 0
        return {
            'booked_occ': otb_rooms / capacity * 100 if capacity else 0,
            'forecast_occ': forecast_occ,
            'adr': adr,
            'revpar': adr * forecast_occ / 100,
        }

    def get_calendar(self, date_from=None, days=14):
        """Everything the pricing calendar shows, as one JSON-serialisable dict."""
        self.ensure_one()
        today = self._get_local_today()
        start = fields.Date.to_date(date_from) or today
        days = max(1, min(days, MAX_CALENDAR_DAYS))
        nights = [start + timedelta(days=i) for i in range(days)]
        rooms = self.room_type_ids
        Forecast = self.env['hotel.rms.forecast']
        Price = self.env['hotel.rms.price']
        forecasts = {f.stay_date: f for f in Forecast.search([
            ('property_id', '=', self.id),
            ('is_current', '=', True),
            ('stay_date', '>=', nights[0]),
            ('stay_date', '<=', nights[-1]),
        ])}
        prices = Price.search([
            ('property_id', '=', self.id),
            ('room_type_id', 'in', rooms.ids),
            ('stay_date', '>=', nights[0]),
            ('stay_date', '<=', nights[-1]),
        ])
        night_list = []
        for night in nights:
            forecast = forecasts.get(night)
            night_list.append({
                'date': fields.Date.to_string(night),
                'weekday': night.weekday(),
                'has_season': bool(self._get_season(night)),
                'events': [e.name for e in self.event_ids if e.date_from <= night <= e.date_to],
                'forecast_occ': forecast.forecast_occ if forecast else None,
                'otb_share': forecast.otb_rooms / forecast.capacity * 100 if forecast else None,
                'confidence_level': forecast.confidence_level if forecast else None,
                'cold_start': bool(forecast) and forecast.method == forecast_engine.COLDSTART_VERSION,
            })
        kpi_fields = ['stay_date', 'otb_rooms', 'forecast_rooms', 'capacity', 'otb_revenue', 'forecast_occ']
        kpi_window = [('stay_date', '>=', today), ('stay_date', '<', today + timedelta(days=KPI_DAYS))]
        current_rows = Forecast.search_fetch([('property_id', '=', self.id), ('is_current', '=', True), *kpi_window], kpi_fields, order='stay_date')
        previous_run = self.env['hotel.rms.run'].search([
            ('property_id', '=', self.id),
            ('state', '=', 'done'),
            ('run_date', '<=', today - timedelta(days=7)),
        ], order='run_date desc, id desc', limit=1)
        previous_rows = previous_run and Forecast.search_fetch(
            [('property_id', '=', self.id), ('run_id', '=', previous_run.id), *kpi_window], kpi_fields)
        last_run = self.env['hotel.rms.run'].search([('property_id', '=', self.id)], limit=1)
        return {
            'property': {
                'id': self.id,
                'name': self.name,
                'currency': {'symbol': self.currency_id.symbol, 'position': self.currency_id.position, 'decimals': self.currency_id.decimal_places},
            },
            'today': fields.Date.to_string(today),
            'date_from': fields.Date.to_string(start),
            'days': days,
            'room_types': [{
                'id': r.id,
                'name': r.name,
                'code': r.code,
                'rooms': r.rooms,
                'caption': r._get_caption(),
                'is_reference': r.derivation == 'reference',
            } for r in rooms],
            'can_decide': self.env.user.has_group('hotel_rms.group_hotel_rms_revenue_manager'),
            'nights': night_list,
            'cells': [price._calendar_cell() for price in prices],
            'kpis': {
                **self._get_kpis(current_rows),
                'forecast_series': current_rows.mapped('forecast_occ'),
                'data_age_days': self.data_age_days if self.last_data_at else None,
            },
            'kpis_previous': previous_rows and self._get_kpis(previous_rows) or None,
            'last_data_at': fields.Datetime.to_string(self.last_data_at) if self.last_data_at else None,
            'to_export_count': Price.search_count([('property_id', '=', self.id), ('to_export', '=', True)]),
            'is_stale': self.is_stale,
            'setup': {key: self[f'setup_{key}'] for key in ('rooms', 'season', 'bookings', 'run', 'done')},
            'last_run': {
                'state': last_run.state,
                'state_label': dict(last_run._fields['state']._description_selection(self.env))[last_run.state],
                'message': last_run.message or '',
            } if last_run else None,
            'publish': {'label': self.env._("Export approved"), 'method': 'action_publish_approved', 'done': self.env._("%s prices exported")},
        }

    def get_insights(self, nights=INSIGHT_DAYS):
        self.ensure_one()
        today = self._get_local_today()
        nights = max(1, min(nights, INSIGHT_DAYS))
        week_ago = today - timedelta(days=WEEK_DAYS)
        year_ago = today - timedelta(days=YEAR_DAYS)
        span = max(nights, HEATMAP_DAYS)
        end = today + timedelta(days=span)
        hotel = ('property_id', '=', self.id)
        index = self._load_night_index(year_ago, end)
        forecasts = {f.stay_date: f.forecast_rooms for f in self.env['hotel.rms.forecast'].search_fetch([hotel, ('is_current', '=', True),
            ('stay_date', '>=', today), ('stay_date', '<', end)], ['stay_date', 'forecast_rooms'])}
        reference = self.room_type_ids.filtered(lambda r: r.derivation == 'reference')[:1]
        recommended = {p.stay_date: p.recommended_rate for p in self.env['hotel.rms.price'].search_fetch([hotel, ('room_type_id', '=', reference.id),
            ('stay_date', '>=', today), ('stay_date', '<', end)], ['stay_date', 'recommended_rate'])}
        capacity = sum(self.room_type_ids.mapped('rooms'))
        days = []
        pulse = dict.fromkeys(['revenue', 'revenue_before', 'new_rooms', 'new_revenue', 'cancel_rooms', 'cancel_revenue'], 0)
        for lead in range(span):
            night = today + timedelta(days=lead)
            booked, revenue = forecast_engine.otb(index, night, today)
            booked_before, revenue_before = forecast_engine.otb(index, night, week_ago)
            days.append({
                'date': fields.Date.to_string(night),
                'booked': booked,
                'pickup': booked - booked_before,
                'capacity': capacity,
                'forecast': forecasts.get(night),
                'price': recommended.get(night) or None,
                'last_year': forecast_engine.otb(index, night - timedelta(days=YEAR_DAYS), year_ago)[0],
            })
            if lead >= nights:
                continue
            pulse['revenue'] += revenue
            pulse['revenue_before'] += revenue_before
            for booking_date, cancel_date, rooms, per_night in index.get(night, ()):
                if week_ago < booking_date <= today and (cancel_date is None or cancel_date > today):
                    pulse['new_rooms'] += rooms
                    pulse['new_revenue'] += per_night
                if cancel_date and week_ago < cancel_date <= today:
                    pulse['cancel_rooms'] += rooms
                    pulse['cancel_revenue'] += per_night
        forecast_days = [day for day in days[:nights] if day['forecast'] is not None]
        month_start = today.replace(day=1)
        local_audit = self.env['hotel.rms.price.audit'].with_context(tz=self.tz or 'UTC')
        decisions = dict(local_audit._read_group([hotel, ('action', 'in', ('accept', 'edit', 'reject')), ('create_date', '>=', month_start)],
            ['action'], ['__count']))
        [(own_rate, recommended_rate)] = local_audit._read_group([hotel, ('action', '=', 'edit'), ('create_date', '>=', month_start)], [],
            ['new_rate:sum', 'recommended_rate:sum'])
        weekly = {}
        for week, action, count in local_audit._read_group(
                [hotel, ('action', 'in', ('accept', 'edit', 'reject')),
                 ('create_date', '>=', today - timedelta(days=ACCURACY_DAYS))],
                ['create_date:week', 'action'], ['__count'], order='create_date:week'):
            counts = weekly.setdefault(week, [0, 0])
            counts[0] += count
            counts[1] += count if action == 'accept' else 0
        accuracy_domain = [hotel, ('has_actual', '=', True), ('lead_days', 'in', ACCURACY_LEADS),
            ('stay_date', '>=', today - timedelta(days=ACCURACY_DAYS)), ('stay_date', '<', today)]
        accuracy = self.env['hotel.rms.forecast']._read_group(accuracy_domain, ['lead_days'], ['error_pts:avg', '__count'])
        accuracy_weeks = self.env['hotel.rms.forecast']._read_group(
            accuracy_domain, ['lead_days', 'stay_date:week'], ['error_pts:avg'], order='stay_date:week')
        latest = self.env['hotel.rms.price.audit'].search_fetch([hotel, ('action', 'in', ('export', 'apply'))],
            ['price_id', 'stay_date', 'room_type_id', 'old_rate', 'new_rate', 'user_id', 'create_date'], limit=LATEST_CHANGES)
        return {
            'today': fields.Date.to_string(today),
            'week_ago': fields.Date.to_string(week_ago),
            'end': fields.Date.to_string(today + timedelta(days=nights)),
            'nights': nights,
            'heatmap_days': HEATMAP_DAYS,
            'pace_days': KPI_DAYS,
            'currency': {'id': self.currency_id.id, 'decimals': self.currency_id.decimal_places},
            'days': days,
            'events': [{'name': event.name, 'date_from': fields.Date.to_string(event.date_from), 'date_to': fields.Date.to_string(event.date_to)}
                for event in self.event_ids if event.date_to >= today and event.date_from < end],
            'pulse': {
                **pulse,
                'forecast_occ': sum(day['forecast'] for day in forecast_days) / (capacity * len(forecast_days)) * 100
                if forecast_days and capacity else None,
            },
            'decisions': {
                'month_start': fields.Date.to_string(month_start),
                'accepted': decisions.get('accept', 0),
                'edited': decisions.get('edit', 0),
                'rejected': decisions.get('reject', 0),
                'own_change_pct': (own_rate - recommended_rate) / recommended_rate * 100
                if recommended_rate else None,
                'acceptance_weeks': [accepted / total * 100 for total, accepted in weekly.values()],
            },
            'accuracy': {
                'ready': sum(count for lead_days, _error_pts, count in accuracy
                             if lead_days == ACCURACY_LEADS[0]) >= 2 * WEEK_DAYS,
                'rooms': {lead_days: error_pts / 100 * capacity for lead_days, error_pts, _count in accuracy},
                'level': {lead_days: 'good' if error_pts <= ACCURACY_GOOD_PTS
                          else 'fair' if error_pts <= ACCURACY_FAIR_PTS else 'poor'
                          for lead_days, error_pts, _count in accuracy},
                'weeks': [{'lead_days': lead_days, 'week': fields.Date.to_string(week), 'rooms': error_pts / 100 * capacity}
                    for lead_days, week, error_pts in accuracy_weeks],
            },
            'latest': [{
                'price_id': audit.price_id.id,
                'night': fields.Date.to_string(audit.stay_date),
                'room': audit.room_type_id.name,
                'old_rate': audit.old_rate,
                'new_rate': audit.new_rate,
                'user': audit.user_id.name,
                'date': fields.Datetime.to_string(audit.create_date),
            } for audit in latest],
        }
