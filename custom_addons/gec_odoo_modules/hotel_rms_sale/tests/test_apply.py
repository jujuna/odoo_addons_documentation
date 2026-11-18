from datetime import time, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DAY, LIST_PRICE, HotelRmsSaleCommon, local_to_utc

NIGHT = 3


@tagged('post_install', '-at_install')
class TestApplyToPricelist(HotelRmsSaleCommon):

    def setUp(self):
        super().setUp()
        self.Item = self.env['product.pricelist.item']
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'done', run.message)

    def _decide(self, offset, rate, room=None, user=None):
        price = self._price(offset)
        if room:
            price = price.filtered(lambda p: p.room_type_id == room)
        price = price.with_user(user or self.pricelist_manager)
        price.decided_rate = rate
        price.action_use_my_price()
        return price

    def _items(self):
        return self.Item.search([('pricelist_id', '=', self.pricelist.id), ('hotel_rms_price_id', '!=', False)])

    def _apply(self, user=None):
        return self.hotel.with_user(user or self.pricelist_manager).action_publish_approved()

    def test_apply_writes_one_fixed_price_item_per_night_and_room_product(self):
        first, second = self._decide(2, 190), self._decide(NIGHT, 217)
        self._apply()
        items = self._items()
        self.assertEqual(len(items), 2)
        for price in (first, second):
            item = items.filtered(lambda i: i.hotel_rms_price_id == price)
            self.assertEqual((item.pricelist_id, item.product_tmpl_id), (self.pricelist, self.room_product))
            self.assertEqual((item.applied_on, item.compute_price, item.min_quantity), ('1_product', 'fixed', 0))
            self.assertEqual(item.fixed_price, price.published_rate)

    def test_the_item_window_is_the_local_day_in_naive_utc(self):
        self._decide(NIGHT, 217)
        self._apply()
        item = self._items()
        day = self.today + NIGHT * DAY
        self.assertEqual(item.date_start, local_to_utc(day, time.min))
        self.assertEqual(item.date_end, local_to_utc(day, time(23, 59, 59)))
        self.assertEqual(item.date_end - item.date_start, timedelta(hours=23, minutes=59, seconds=59))
        self.assertEqual(item.date_start.hour, 20)

    def test_the_pricelist_sells_the_applied_price_on_its_night_only(self):
        self._decide(NIGHT, 217)
        self._apply()
        self.assertEqual(self._price_on(NIGHT), 217)
        self.assertEqual(self._price_on(NIGHT - 1), LIST_PRICE)
        self.assertEqual(self._price_on(NIGHT + 1), LIST_PRICE)

    def test_apply_marks_the_prices_exported_and_writes_audit_rows(self):
        price = self._decide(NIGHT, 217)
        self.assertTrue(price.to_export)
        result = self._apply()
        self.assertFalse(result)
        self.assertEqual((price.to_export, price.exported_rate), (False, 217))
        audit = price.audit_ids.sorted('id')[-1]
        self.assertEqual((audit.action, audit.old_rate, audit.new_rate, audit.user_id),
                         ('apply', LIST_PRICE, 217, self.pricelist_manager))

    def test_applying_twice_updates_the_same_item(self):
        price = self._decide(NIGHT, 217)
        self._apply()
        item = self._items()
        self._decide(NIGHT, 230)
        self._apply()
        self.assertEqual(self._items(), item)
        self.assertEqual(item.fixed_price, 230)
        self.assertEqual(self._price_on(NIGHT), 230)
        self.assertEqual(self.Item.search_count([('hotel_rms_price_id', '=', price.id)]), 1)

    def test_nothing_to_apply_makes_no_item(self):
        self._apply()
        self.assertFalse(self._items())

    def test_past_nights_are_not_applied(self):
        past = self.env['hotel.rms.price'].create({
            'property_id': self.hotel.id, 'room_type_id': self.room.id, 'stay_date': self.today - DAY,
            'published_rate': 100, 'exported_rate': 0})
        self.assertTrue(past.to_export)
        self._decide(NIGHT, 217)
        self._apply()
        self.assertEqual(len(self._items()), 1)
        self.assertFalse(self._items().hotel_rms_price_id == past)
        self.assertTrue(past.to_export)

    def test_tonight_is_applied(self):
        self._decide(0, 217)
        self._apply()
        self.assertEqual(self._items().hotel_rms_price_id, self._price(0))

    def test_a_night_that_is_not_for_sale_is_not_applied(self):
        night = self._price(2)
        night.write({'not_for_sale': True, 'published_rate': 100})
        self.assertTrue(night.to_export)
        self._apply()
        self.assertFalse(self._items())
        self.assertTrue(night.to_export)

    def test_apply_needs_the_pricelist_rights(self):
        price = self._decide(NIGHT, 217, user=self.manager)
        with self.assertRaises(UserError):
            self._apply(user=self.manager)
        self.assertFalse(self._items())
        self.assertTrue(price.to_export)

    def test_each_room_product_gets_its_own_item(self):
        suite_product = self._create_room_product("Suite room")
        suite = self.env['hotel.rms.room.type'].create({
            'property_id': self.hotel.id, 'name': "Suite", 'code': 'STE', 'rooms': 2, 'derivation': 'amount',
            'derive_value': 50, 'product_tmpl_id': suite_product.id})
        run = self.hotel._run_engine()
        self.assertEqual(run.state, 'done', run.message)
        self._decide(NIGHT, 217, room=self.room)
        self._decide(NIGHT, 267, room=suite)
        self._apply()
        by_product = {item.product_tmpl_id: item.fixed_price for item in self._items()}
        self.assertEqual(by_product, {self.room_product: 217, suite_product: 267})

    def test_the_calendar_counts_only_the_prices_the_apply_would_write(self):
        self._decide(NIGHT, 217)
        past = self.env['hotel.rms.price'].create({
            'property_id': self.hotel.id, 'room_type_id': self.room.id, 'stay_date': self.today - DAY,
            'published_rate': 100, 'exported_rate': 0})
        self.assertTrue(past.to_export)
        calendar = self.hotel.with_user(self.pricelist_manager).get_calendar(self.today, 3)
        self.assertEqual(calendar['to_export_count'], 1)
        self._apply()
        self.assertEqual(self.hotel.get_calendar(self.today, 3)['to_export_count'], 0)

    def test_without_a_pricelist_the_core_csv_export_runs(self):
        self.hotel.pricelist_id = False
        result = self.hotel.action_publish_approved()
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertFalse(self._items())
