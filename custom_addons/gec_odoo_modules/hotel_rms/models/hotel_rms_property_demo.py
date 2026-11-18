import random
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.tools.translate import _lt

from ..engine import forecast as forecast_engine
from ..engine import pricing as pricing_engine
from .hotel_rms_property import DOW_FIELDS

DAY = timedelta(days=1)
DEMO_SEED = 42
DEMO_ROOMS = (  # name, code, rooms, priced as, amount or percent above the reference room
    (_lt("Standard"), 'STD', 12, 'reference', 0),
    (_lt("Deluxe"), 'DLX', 6, 'amount', 40),
    (_lt("Suite"), 'SUI', 2, 'percent', 60),
)
DEMO_SEASONS = {  # level: name, base, minimum, maximum price, expected occupancy %
    'low': (_lt("Low season"), 85, 70, 120, 55),
    'mid': (_lt("Mid season"), 105, 85, 150, 70),
    'high': (_lt("High season"), 135, 110, 190, 85),
}
DEMO_MONTH_LEVEL = {1: 'low', 2: 'low', 3: 'low', 4: 'low', 5: 'mid', 6: 'high', 7: 'high', 8: 'high', 9: 'high', 10: 'mid', 11: 'low', 12: 'mid'}
DEMO_SEASONS_FROM_DAYS = 400
DEMO_SEASONS_TO_DAYS = 150
DEMO_WEEKDAY_PCT = {'dow_fri': 10, 'dow_sat': 15}
DEMO_STALE_AFTER_DAYS = 3650
DEMO_EVENTS = (  # name, category, price impact %, first night in days from today, nights
    (_lt("City Festival"), 'event', 15, 20, 3),
    (_lt("Business Conference"), 'event', 10, 45, 3),
    (_lt("Public Holiday"), 'holiday', 0, 70, 1),
)
DEMO_FIRST_ARRIVAL_DAYS = 395
DEMO_LAST_ARRIVAL_DAYS = 120
DEMO_STAYS = (1, 1, 2, 2, 2, 3, 3, 4, 5, 7)
DEMO_LEAD_MEAN_DAYS = 28
DEMO_CANCEL_RATE = 0.1
DEMO_WEEKEND_DAYS = (4, 5)
DEMO_WEEKEND_DEMAND = 1.2
DEMO_WEEKDAY_DEMAND = 0.95
DEMO_RATE_NOISE = (0.9, 1.1)
DEMO_CHANNELS = ('Booking.com', _lt("Direct"), 'Expedia', _lt("Phone"))
DEMO_FORECAST_DAYS = 28
DEMO_ACCEPTED = 6
DEMO_QUICK = 2
DEMO_QUICK_PCT = 5
DEMO_REJECTED = 1


class HotelRmsProperty(models.Model):
    _inherit = 'hotel.rms.property'

    @api.model
    def action_load_demo(self):
        self.check_access('unlink')
        demo = self.search([('is_demo', '=', True), ('company_id', '=', self.env.company.id)], limit=1)
        return (demo or self._create_demo_hotel()).action_open_calendar()

    def action_remove_demo(self):
        """Everything under the demo hotel goes with it (ondelete cascade)."""
        self.filtered('is_demo').unlink()
        return self.env['ir.actions.actions']._for_xml_id('hotel_rms.action_hotel_rms_property')

    def _create_demo_hotel(self):
        hotel = self.with_context(tracking_disable=True, mail_create_nolog=True).create({
            'name': self.env._("Demo Hotel (sample data)"),
            'company_id': self.env.company.id,
            'is_demo': True,
            'last_data_at': fields.Datetime.now(),
            'stale_after_days': DEMO_STALE_AFTER_DAYS,
            **DEMO_WEEKDAY_PCT,
            'room_type_ids': [Command.create({
                'name': self.env._(name),
                'code': code,
                'rooms': rooms,
                'derivation': derivation,
                'derive_value': value,
                'sequence': index,
            }) for index, (name, code, rooms, derivation, value) in enumerate(DEMO_ROOMS, 1)],
        })
        today = hotel._get_local_today()
        last_night = today + timedelta(days=DEMO_SEASONS_TO_DAYS)
        seasons = []
        night = today - timedelta(days=DEMO_SEASONS_FROM_DAYS)
        while night <= last_night:
            level = DEMO_MONTH_LEVEL[night.month]
            month_end = min(night + relativedelta(day=31), last_night)
            if seasons and seasons[-1][0] == level:
                seasons[-1][2] = month_end
            else:
                seasons.append([level, night, month_end])
            night = month_end + DAY
        hotel.write({
            'season_ids': [Command.create({
                'name': self.env._(DEMO_SEASONS[level][0]),
                'date_from': date_from,
                'date_to': date_to,
                'base_rate': DEMO_SEASONS[level][1],
                'min_rate': DEMO_SEASONS[level][2],
                'max_rate': DEMO_SEASONS[level][3],
                'expected_occ_pct': DEMO_SEASONS[level][4],
            }) for level, date_from, date_to in seasons],
            'event_ids': [Command.create({
                'name': self.env._(name),
                'category': category,
                'impact_pct': impact,
                'date_from': today + timedelta(days=first),
                'date_to': today + timedelta(days=first + nights - 1),
            }) for name, category, impact, first, nights in DEMO_EVENTS],
        })
        self.env['hotel.rms.reservation'].create(self._prepare_demo_reservations(hotel, today))
        self._create_demo_forecast_history(hotel, today)
        hotel._run_engine()
        self._create_demo_decisions(hotel)
        return hotel

    def _prepare_demo_reservations(self, hotel, today):
        """Seeded bookings, the same every time: demand follows season and weekday, rooms are never overbooked."""
        rng = random.Random(DEMO_SEED)
        average_stay = sum(DEMO_STAYS) / len(DEMO_STAYS)
        taken = {}
        vals_list = []
        arrival = today - timedelta(days=DEMO_FIRST_ARRIVAL_DAYS)
        while arrival < today + timedelta(days=DEMO_LAST_ARRIVAL_DAYS):
            season = hotel._get_season(arrival)
            weekend = arrival.weekday() in DEMO_WEEKEND_DAYS
            reference_rate = season.base_rate * (1 + hotel[DOW_FIELDS[arrival.weekday()]] / 100)
            for room in hotel.room_type_ids:
                demand = room.rooms * season.expected_occ_pct / 100 * (DEMO_WEEKEND_DEMAND if weekend else DEMO_WEEKDAY_DEMAND) / average_stay
                rate = (reference_rate + room.derive_value if room.derivation == 'amount' else reference_rate * (1 + room.derive_value / 100))
                for _ in range(int(demand + rng.random())):
                    nights = [arrival + timedelta(days=i) for i in range(rng.choice(DEMO_STAYS))]
                    if any(taken.get((room.id, night), 0) >= room.rooms for night in nights):
                        continue
                    lead = int(rng.expovariate(1 / DEMO_LEAD_MEAN_DAYS))
                    booked = arrival - timedelta(days=lead)
                    if booked > today:
                        continue
                    cancel_date = booked + timedelta(days=rng.randint(0, lead))
                    cancelled = rng.random() < DEMO_CANCEL_RATE and cancel_date <= today
                    if not cancelled:
                        for night in nights:
                            taken[room.id, night] = taken.get((room.id, night), 0) + 1
                    vals_list.append({
                        'property_id': hotel.id,
                        'source_ref': f"DEMO-{len(vals_list) + 1:05d}",
                        'room_type_id': room.id,
                        'booking_date': booked,
                        'arrival': arrival,
                        'departure': arrival + timedelta(days=len(nights)),
                        'rooms': 1,
                        'revenue': round(rate * len(nights) * rng.uniform(*DEMO_RATE_NOISE), 2),
                        'status': 'cancelled' if cancelled else 'confirmed',
                        'cancel_date': cancel_date if cancelled else False,
                        'channel': self.env._(rng.choice(DEMO_CHANNELS)),
                    })
            arrival += DAY
        return vals_list

    def _create_demo_forecast_history(self, hotel, today):
        """One finished run and its forecasts for each of the last days, as the engine would have made them that day."""
        capacity = sum(hotel.room_type_ids.mapped('rooms'))
        index = hotel._load_night_index(today - timedelta(days=DEMO_FIRST_ARRIVAL_DAYS), today + timedelta(days=hotel.horizon_days))
        [(history_start,)] = self.env['hotel.rms.reservation']._read_group([('property_id', '=', hotel.id)], [], ['booking_date:min'])
        booking_curve = sorted((p.x, p.value / 100) for p in hotel.booking_point_ids)
        days = [today - timedelta(days=i) for i in range(DEMO_FORECAST_DAYS, 0, -1)]
        rows_by_day = {}
        for day in days:
            rows = rows_by_day[day] = []
            for lead in range(hotel.horizon_days):
                night = day + timedelta(days=lead)
                refs = forecast_engine.comparable_dates(night, day, hotel.ref_window_days, hotel.ref_years, hotel.recent_weeks)
                result = forecast_engine.forecast_v1(index, night, day, capacity, refs, hotel.min_refs, history_start)
                season = hotel._get_season(night)
                if result is None and season and booking_curve:
                    booked, revenue = forecast_engine.otb(index, night, day)
                    result = forecast_engine.coldstart_v1(booked, revenue, capacity, season.expected_occ_pct / 100, lead, booking_curve)
                if not result:
                    continue
                score, level = forecast_engine.confidence(result['method'], result['refs'], 0)
                rows.append({
                    'property_id': hotel.id,
                    'run_date': day,
                    'stay_date': night,
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
                })
        now = fields.Datetime.now()
        runs = self.env['hotel.rms.run'].create([{
            'property_id': hotel.id,
            'run_date': day,
            'started_at': now - (today - day),
            'state': 'done',
            'forecast_version': forecast_engine.FORECAST_VERSION,
            'price_version': pricing_engine.PRICE_VERSION,
            'nights': len(rows_by_day[day]),
        } for day in days])
        self.env['hotel.rms.forecast'].create([dict(vals, run_id=run.id) for run, day in zip(runs, days) for vals in rows_by_day[day]])

    def _create_demo_decisions(self, hotel):
        """Decide the first prices through the real actions, so Price History and Decisions have content."""
        prices = self.env['hotel.rms.price'].search([('property_id', '=', hotel.id), ('state', '=', 'pending')], order='stay_date, id',
            limit=DEMO_ACCEPTED + DEMO_QUICK + DEMO_REJECTED)
        prices[:DEMO_ACCEPTED].action_accept()
        prices[DEMO_ACCEPTED:DEMO_ACCEPTED + DEMO_QUICK].action_quick_price(DEMO_QUICK_PCT)
        hotel.action_publish_approved()
        prices[DEMO_ACCEPTED + DEMO_QUICK:].action_reject()
