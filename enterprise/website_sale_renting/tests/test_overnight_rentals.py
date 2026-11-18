# Part of Odoo. See LICENSE file for full copyright and licensing details.

from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.website_sale_renting.tests.common import WebsiteSaleRentingCommon


@tagged("post_install", "-at_install")
class TestOvernightRental(WebsiteSaleRentingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.hotel_room_early_check_in = cls._create_product(
            name="Hotel Room Early Birds",
            rent_periodicity="nights",
            list_price=90,
            pickup_time=15,
            return_time=10,
        )
        cls.hotel_room_late_check_in = cls._create_product(
            name="Hotel Room Night Owls",
            rent_periodicity="nights",
            list_price=70,
            pickup_time=18,
            return_time=9,
        )
        cls.bike_for_a_day = cls._create_product(
            name="Bike", rent_periodicity="days", list_price=20.0
        )

    def test_add_to_cart_with_overnight_period(self):
        """Overnight products can be added to cart only if:
        - cart is empty
        - cart contains the same product
        - cart contains an overnight product with the same period."""
        with freeze_time("2025-01-01"):
            with self.mock_request() as request:
                # use partner_a from the Renting Company
                self.env.user.partner_id = self.partner
                website = request.env.website
                ro = website._create_cart()
                ro._cart_add(product_id=self.bike_for_a_day.product_variant_id.id, quantity=1)
                self.assertFalse(
                    self.hotel_room_early_check_in._is_add_to_cart_allowed(),
                    "Overnight product should not be addable to cart with non-overnight product",
                )
                ro._cart_update_line_quantity(line_id=ro.order_line[0].id, quantity=0)
                self.assertTrue(
                    self.hotel_room_early_check_in._is_add_to_cart_allowed(),
                    "Overnight product should be addable to empty cart",
                )
                ro._cart_add(product_id=self.hotel_room_early_check_in.id, quantity=1)
                self.assertFalse(
                    self.hotel_room_late_check_in._is_add_to_cart_allowed(),
                    "Overnight product with different period should not be addable to cart",
                )
                self.assertTrue(
                    self.hotel_room_early_check_in._is_add_to_cart_allowed(),
                    "Overnight product with same period should be addable to cart",
                )

    @freeze_time("2025-01-01")
    def test_default_renting_dates_keep_utc_offset_on_product_page(self):
        """The product page inputs are read in the browser timezone before the daterange picker
        formats them, so the default renting dates must be rendered with their UTC offset."""
        self.website.sudo().tz = "Europe/Brussels"
        with self.mock_request(cookies={"tz": self.website.tz}) as request:
            combination_info = self.bike_for_a_day.product_tmpl_id.with_context(
                request.env.context
            )._get_combination_info()
            self.assertEqual(
                str(combination_info["default_start_date"]), "2025-01-01 23:00:00+00:00"
            )
            self.assertEqual(
                str(combination_info["default_end_date"]), "2025-01-02 23:00:00+00:00"
            )
