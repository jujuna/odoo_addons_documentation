import itertools
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase

DAY = timedelta(days=1)
REFERENCES = itertools.count(1)


class HotelRmsCommon(TransactionCase):
    """A hotel of 10 rooms (8 Double as the reference, 2 Suite priced 50 above it) with a season and fresh data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.manager = cls._create_user('rms_manager', 'hotel_rms.group_hotel_rms_revenue_manager')
        cls.viewer = cls._create_user('rms_viewer', 'hotel_rms.group_hotel_rms_user')
        cls.hotel = cls.env['hotel.rms.property'].create({
            'name': "Test Hotel", 'company_id': cls.company.id, 'tz': 'UTC', 'horizon_days': 10,
        })
        cls.today = cls.hotel._get_local_today()
        Room = cls.env['hotel.rms.room.type']
        cls.double = Room.create({'property_id': cls.hotel.id, 'name': "Double", 'code': 'DBL', 'rooms': 8})
        cls.suite = Room.create({'property_id': cls.hotel.id, 'name': "Suite", 'code': 'STE', 'rooms': 2,
                                 'derivation': 'amount', 'derive_value': 50})
        cls.season = cls.env['hotel.rms.season'].create({
            'property_id': cls.hotel.id, 'name': "All year", 'date_from': cls.today - 30 * DAY,
            'date_to': cls.today + 365 * DAY, 'base_rate': 200, 'min_rate': 100, 'max_rate': 400,
            'expected_occ_pct': 50,
        })
        cls.hotel.last_data_at = fields.Datetime.now()

    @classmethod
    def _create_user(cls, login, group_xmlid):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': f'{login}@example.com',
            'group_ids': [Command.set([cls.env.ref(group_xmlid).id])],
        })

    def _run(self, hotel=None):
        run = (hotel or self.hotel)._run_engine()
        self.assertEqual(run.state, 'done', run.message)
        return run

    def _price(self, offset, room=None, hotel=None):
        return self.env['hotel.rms.price'].search([
            ('property_id', '=', (hotel or self.hotel).id), ('stay_date', '=', self.today + offset * DAY),
            ('room_type_id', '=', (room or self.double).id)])

    def _prices(self, hotel=None):
        return self.env['hotel.rms.price'].search([('property_id', '=', (hotel or self.hotel).id)])

    def _forecasts(self, hotel=None):
        return self.env['hotel.rms.forecast'].search([('property_id', '=', (hotel or self.hotel).id)])

    def _snapshot(self):
        return {(price.stay_date, price.room_type_id.code): (price.recommended_rate, price.raw_target_rate,
                                                              price.action, price.state)
                for price in self._prices()}

    def _add_reservation(self, arrival, nights=1, rooms=1, booked=None, **values):
        return self.env['hotel.rms.reservation'].create({
            'property_id': self.hotel.id, 'room_type_id': self.double.id, 'arrival': arrival,
            'departure': arrival + nights * DAY, 'booking_date': booked or arrival, 'rooms': rooms,
            'source_ref': f"TEST-{next(REFERENCES)}", **values})
