from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DAY, LIST_PRICE, HotelRmsSaleCommon


@tagged('post_install', '-at_install')
class TestPriceSync(HotelRmsSaleCommon):

    def test_every_night_of_the_horizon_gets_a_price_row_from_the_pricelist(self):
        self._sync()
        prices = self._prices()
        self.assertEqual(sorted(prices.mapped('stay_date')), [self.today + i * DAY for i in range(6)])
        self.assertEqual(set(prices.mapped('room_type_id')), {self.room})
        self.assertEqual(set(prices.mapped('published_rate')), {LIST_PRICE})
        self.assertEqual(set(prices.mapped('exported_rate')), {LIST_PRICE})
        self.assertFalse(any(prices.mapped('to_export')))

    def test_the_price_of_a_night_is_the_pricelist_price_of_that_night(self):
        self._set_night_price(2, 180)
        self._sync()
        self.assertEqual((self._price(2).published_rate, self._price(2).exported_rate), (180, 180))
        self.assertEqual((self._price(1).published_rate, self._price(3).published_rate), (LIST_PRICE, LIST_PRICE))

    def test_a_changed_pricelist_price_is_read_again(self):
        item = self._set_night_price(2, 180)
        self._sync()
        item.fixed_price = 190
        self._sync()
        self.assertEqual((self._price(2).published_rate, self._price(2).exported_rate), (190, 190))

    def test_a_price_waiting_to_be_published_is_not_overwritten(self):
        self._sync()
        waiting = self._price(2)
        waiting.published_rate = 200
        self._set_night_price(2, 180)
        self._sync()
        self.assertEqual((waiting.published_rate, waiting.exported_rate, waiting.to_export), (200, LIST_PRICE, True))

    def test_a_zero_price_is_not_for_sale(self):
        self._set_night_price(2, 0)
        self._sync()
        night = self._price(2)
        self.assertTrue(night.not_for_sale)
        self.assertEqual((night.published_rate, night.recommended_rate, night.state), (0, 0, 'hold'))
        self.assertFalse(self._price(3).not_for_sale)

    def test_a_night_that_is_not_for_sale_is_marked_in_the_calendar_and_panel(self):
        self._set_night_price(2, 0)
        self._sync()
        night = self._price(2).with_user(self.manager)
        self.assertTrue(night._calendar_cell()['not_for_sale'])
        actions = night.get_panel_data()['actions']
        self.assertEqual((actions['accept'], actions['use_my_price'], actions['reject']), (False, False, False))
        self.assertTrue(actions['lock'])

    def test_a_night_that_is_not_for_sale_cannot_be_decided(self):
        self._set_night_price(2, 0)
        self._sync()
        night = self._price(2)
        night.decided_rate = 200
        night.action_use_my_price()
        night.action_accept()
        self.assertEqual((night.state, night.published_rate), ('hold', 0))

    def test_the_engine_leaves_a_night_that_is_not_for_sale_alone(self):
        self._set_night_price(2, 0)
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'done', run.message)
        night = self._price(2)
        self.assertEqual((night.not_for_sale, night.recommended_rate, night.action, night.state),
                         (True, 0, False, 'hold'))
        self.assertTrue(self._price(3).recommended_rate)

    def test_a_night_becomes_for_sale_again_when_the_price_returns(self):
        item = self._set_night_price(2, 0)
        self._sync()
        item.fixed_price = 180
        self._sync()
        self.assertEqual((self._price(2).not_for_sale, self._price(2).published_rate), (False, 180))

    def test_without_a_pricelist_no_prices_are_read(self):
        self.hotel.pricelist_id = False
        self._sync()
        self.assertFalse(self._prices())
        self.assertTrue(self.hotel.last_data_at)

    def test_a_pricelist_hotel_refuses_a_rates_file(self):
        imp = self._rates_import()
        with self.assertRaises(UserError):
            imp.action_import()
        self.assertFalse(self._prices())

    def test_a_hotel_without_a_pricelist_accepts_a_rates_file(self):
        self.hotel.pricelist_id = False
        imp = self._rates_import()
        imp.action_import()
        self.assertEqual(imp.state, 'done', imp.errors)

    def test_the_calendar_names_the_pricelist_as_the_target(self):
        calendar = self.hotel.get_calendar(self.today, 3)
        self.assertEqual(calendar['publish']['label'], "Apply to pricelist")
        self.assertEqual(calendar['publish']['method'], 'action_publish_approved')

    def test_the_calendar_of_a_hotel_without_a_pricelist_keeps_the_export(self):
        self.hotel.pricelist_id = False
        self.assertEqual(self.hotel.get_calendar(self.today, 3)['publish']['label'], "Export approved")
