import psycopg2

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import DAY, HotelRmsCommon


@tagged('post_install', '-at_install')
class TestSecurity(HotelRmsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hotel._run_engine()
        cls.price = cls.env['hotel.rms.price'].search([
            ('property_id', '=', cls.hotel.id), ('stay_date', '=', cls.today + 2 * DAY),
            ('room_type_id', '=', cls.double.id)])
        cls.price.action_accept()
        cls.audit = cls.price.audit_ids

    def test_a_viewer_reads_but_cannot_decide(self):
        price = self._price(3).with_user(self.viewer)
        price.read(['recommended_rate'])
        for method in ('action_accept', 'action_reject', 'action_lock'):
            with self.subTest(method=method), self.assertRaises(AccessError):
                getattr(price, method)()
        self.assertEqual(self._price(3).state, 'pending')

    def test_a_viewer_cannot_set_a_price_of_their_own(self):
        with self.assertRaises(AccessError):
            self._price(3).with_user(self.viewer).write({'decided_rate': 200})

    def test_a_viewer_cannot_create_audit_rows(self):
        with self.assertRaises(AccessError):
            self.env['hotel.rms.price.audit'].with_user(self.viewer).create({
                'price_id': self.price.id, 'action': 'accept'})

    def test_a_revenue_manager_cannot_touch_audit_rows_directly(self):
        Audit = self.env['hotel.rms.price.audit'].with_user(self.manager)
        with self.assertRaises(AccessError):
            Audit.create({'price_id': self.price.id, 'action': 'accept'})
        with self.assertRaises(AccessError):
            self.audit.with_user(self.manager).write({'note': "edited"})
        with self.assertRaises(AccessError):
            self.audit.with_user(self.manager).unlink()

    def test_a_revenue_manager_reads_the_audit_rows(self):
        self.assertEqual(self.audit.with_user(self.manager).user_id, self.env.user)

    def test_a_revenue_manager_decides_and_the_audit_row_holds_their_name(self):
        price = self._price(3).with_user(self.manager)
        price.action_accept()
        self.assertEqual(price.audit_ids.user_id, self.manager)

    def test_a_revenue_manager_cannot_delete_prices_or_the_hotel(self):
        with self.assertRaises(AccessError):
            self._price(3).with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            self.hotel.with_user(self.manager).unlink()

    def test_a_room_type_with_prices_cannot_be_deleted(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.suite.unlink()

    def test_a_room_type_with_reservations_cannot_be_deleted(self):
        self._add_reservation(self.today, room_type_id=self.double.id)
        self.env['hotel.rms.price'].search([('room_type_id', '=', self.double.id)]).unlink()
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.double.unlink()


@tagged('post_install', '-at_install')
class TestCompanyIsolation(HotelRmsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': "Hotel Company B"})
        cls.user_b = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': "rms_user_b", 'login': 'rms_user_b', 'email': 'rms_user_b@example.com',
            'company_id': cls.company_b.id, 'company_ids': [Command.set(cls.company_b.ids)],
            'group_ids': [Command.set([cls.env.ref('hotel_rms.group_hotel_rms_revenue_manager').id])],
        })
        cls.hotel_b = cls.env['hotel.rms.property'].create({
            'name': "Hotel B", 'company_id': cls.company_b.id, 'tz': 'UTC', 'horizon_days': 5})
        cls.env['hotel.rms.room.type'].create({'property_id': cls.hotel_b.id, 'name': "Single", 'code': 'SGL'})
        cls.env['hotel.rms.season'].create({
            'property_id': cls.hotel_b.id, 'name': "All year", 'date_from': cls.today - DAY,
            'date_to': cls.today + 30 * DAY, 'base_rate': 90, 'min_rate': 50, 'max_rate': 150})
        cls.hotel_b.last_data_at = cls.hotel.last_data_at
        cls.hotel._run_engine()
        cls.hotel_b.with_company(cls.company_b)._run_engine()
        cls.prices_a = cls.env['hotel.rms.price'].search([('property_id', '=', cls.hotel.id)])
        cls.prices_b = cls.env['hotel.rms.price'].search([('property_id', '=', cls.hotel_b.id)])

    def test_both_hotels_have_prices(self):
        self.assertEqual((len(self.prices_a), len(self.prices_b)), (20, 5))

    def test_the_user_of_company_b_searches_only_company_b(self):
        found = self.env['hotel.rms.price'].with_user(self.user_b).search([])
        self.assertEqual(found, self.prices_b)

    def test_the_user_of_company_b_cannot_read_a_price_of_company_a(self):
        price = self.prices_a[:1].with_user(self.user_b)
        self.assertFalse(price.has_access('read'))
        with self.assertRaises(AccessError):
            price.read(['recommended_rate'])

    def test_the_user_of_company_b_cannot_decide_a_price_of_company_a(self):
        with self.assertRaises(AccessError):
            self.prices_a[:1].with_user(self.user_b).action_accept()

    def test_the_user_of_company_b_gets_nothing_of_company_a_from_the_calendar(self):
        with self.assertRaises(AccessError):
            self.hotel.with_user(self.user_b).get_calendar(self.today, 5)

    def test_the_calendar_of_company_b_holds_only_its_own_prices(self):
        calendar = self.hotel_b.with_user(self.user_b).get_calendar(self.today, 5)
        self.assertEqual({cell['id'] for cell in calendar['cells']}, set(self.prices_b.ids))

    def test_the_other_models_are_isolated_too(self):
        for model in ('hotel.rms.forecast', 'hotel.rms.run', 'hotel.rms.price.audit', 'hotel.rms.reservation',
                      'hotel.rms.season', 'hotel.rms.room.type', 'hotel.rms.curve.point', 'hotel.rms.event',
                      'hotel.rms.import', 'hotel.rms.property'):
            with self.subTest(model=model):
                rows = self.env[model].with_user(self.user_b).search([])
                self.assertFalse(rows.filtered(lambda r: r.company_id == self.company), model)

    def test_the_user_of_company_b_cannot_run_the_engine_of_company_a(self):
        with self.assertRaises(AccessError):
            self.hotel.with_user(self.user_b).action_run_engine()
