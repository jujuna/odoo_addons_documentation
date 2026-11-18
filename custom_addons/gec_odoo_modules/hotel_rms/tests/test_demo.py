from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import DAY, HotelRmsCommon

CHILD_MODELS = ('hotel.rms.room.type', 'hotel.rms.season', 'hotel.rms.event', 'hotel.rms.curve.point',
                'hotel.rms.reservation', 'hotel.rms.forecast', 'hotel.rms.run', 'hotel.rms.price',
                'hotel.rms.price.audit')


@tagged('post_install', '-at_install')
class TestDemo(HotelRmsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls._create_user('rms_admin', 'hotel_rms.group_hotel_rms_manager')
        cls.hotel._run_engine()
        cls.env['hotel.rms.price'].search([
            ('property_id', '=', cls.hotel.id), ('stay_date', '=', cls.today + 2 * DAY),
            ('room_type_id', '=', cls.double.id)]).action_accept()
        cls.real_counts = cls._counts(cls.hotel)
        cls.Property = cls.env['hotel.rms.property'].with_user(cls.admin)
        cls.action = cls.Property.action_load_demo()
        cls.demo = cls.env['hotel.rms.property'].search([('is_demo', '=', True)])

    @classmethod
    def _counts(cls, hotel):
        return {model: cls.env[model].search_count([('property_id', '=', hotel.id)]) for model in CHILD_MODELS}

    def test_load_creates_one_demo_hotel_and_opens_its_calendar(self):
        self.assertEqual(len(self.demo), 1)
        self.assertEqual(self.demo.name, "Demo Hotel (sample data)")
        self.assertEqual(self.demo.company_id, self.company)
        self.assertEqual(self.action['tag'], 'hotel_rms.pricing_calendar')
        self.assertEqual(self.action['context'], {'property_id': self.demo.id})

    def test_the_demo_hotel_has_rooms_seasons_and_events_around_today(self):
        today = self.demo._get_local_today()
        self.assertEqual(sum(self.demo.room_type_ids.mapped('rooms')), 20)
        self.assertEqual(len(self.demo.room_type_ids.filtered(lambda r: r.derivation == 'reference')), 1)
        self.assertEqual(min(self.demo.season_ids.mapped('date_from')), today - 400 * DAY)
        self.assertEqual(max(self.demo.season_ids.mapped('date_to')), today + 150 * DAY)
        self.assertTrue(all(self.demo._get_season(today + i * DAY) for i in range(-400, 151)))
        self.assertEqual(len(self.demo.event_ids), 3)
        self.assertTrue(all(today < event.date_from <= today + 90 * DAY for event in self.demo.event_ids))

    def test_the_demo_hotel_has_bookings_forecasts_and_decisions(self):
        today = self.demo._get_local_today()
        reservations = self.env['hotel.rms.reservation'].search([('property_id', '=', self.demo.id)])
        self.assertGreater(len(reservations), 500)
        self.assertEqual(set(reservations.mapped('status')), {'confirmed', 'cancelled'})
        self.assertTrue(all(ref.startswith('DEMO-') for ref in reservations.mapped('source_ref')))
        self.assertTrue(self.demo.last_data_at)
        runs = self.env['hotel.rms.run'].search([('property_id', '=', self.demo.id)])
        self.assertEqual(set(runs.mapped('state')), {'done'})
        self.assertEqual(len(runs), 29)
        history = self.env['hotel.rms.forecast'].search([('property_id', '=', self.demo.id), ('run_date', '<', today)])
        self.assertEqual(set(history.mapped('run_date')), {today - i * DAY for i in range(1, 29)})
        self.assertTrue(history.filtered('has_actual'))
        audits = self.env['hotel.rms.price.audit'].search([('property_id', '=', self.demo.id)])
        self.assertEqual(set(audits.mapped('action')), {'accept', 'edit', 'reject', 'export'})
        self.assertTrue(self.demo.get_insights()['accuracy']['ready'])

    def test_load_leaves_the_real_hotel_alone(self):
        self.assertEqual(self._counts(self.hotel), self.real_counts)
        self.assertFalse(self.hotel.is_demo)

    def test_a_second_load_returns_the_same_demo_hotel(self):
        action = self.Property.action_load_demo()
        self.assertEqual(action['context'], {'property_id': self.demo.id})
        self.assertEqual(self.env['hotel.rms.property'].search_count([('is_demo', '=', True)]), 1)

    def test_remove_deletes_the_demo_hotel_with_everything_under_it(self):
        demo_id = self.demo.id
        action = self.demo.with_user(self.admin).action_remove_demo()
        self.assertEqual(action['res_model'], 'hotel.rms.property')
        self.assertFalse(self.env['hotel.rms.property'].search([('is_demo', '=', True)]))
        for model in CHILD_MODELS:
            with self.subTest(model=model):
                self.assertFalse(self.env[model].search_count([('property_id', '=', demo_id)]))

    def test_remove_keeps_the_real_hotel_and_its_audit_rows(self):
        self.demo.with_user(self.admin).action_remove_demo()
        self.assertTrue(self.hotel.exists())
        self.assertEqual(self._counts(self.hotel), self.real_counts)
        self.assertTrue(self.real_counts['hotel.rms.price.audit'])

    def test_the_demo_data_menu_loads_and_opens_the_demo_hotel(self):
        action = self.env.ref('hotel_rms.action_hotel_rms_demo').with_user(self.admin).run()
        self.assertEqual(action['context'], {'property_id': self.demo.id})

    def test_a_revenue_manager_cannot_load_or_remove_the_demo_hotel(self):
        with self.assertRaises(AccessError):
            self.env['hotel.rms.property'].with_user(self.manager).action_load_demo()
        with self.assertRaises(AccessError):
            self.demo.with_user(self.manager).action_remove_demo()
