"""_validate_before_save, the gate between Odoo and RS.GE. Per-type rules encode RS behaviour: internal transport
waives the buyer, only road types carry a driver, sub-waybills inherit the parent's transport."""

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestValidateBeforeSave(RsWaybillCommon):

    def assertRefuses(self, waybill, fragment):
        with self.assertRaises(UserError) as e:
            waybill._validate_before_save()
        self.assertIn(fragment, e.exception.args[0])

    def test_complete_waybill_passes(self):
        waybill = self.make_waybill()
        self.add_line(waybill)
        waybill._validate_before_save()

    def test_goods_are_required(self):
        self.assertRefuses(self.make_waybill(), 'At least one product line')

    def test_every_line_needs_a_product(self):
        waybill = self.make_waybill()
        self.add_line(waybill, product_id=False)
        self.assertRefuses(waybill, 'missing a product')

    def test_waybill_type_is_required(self):
        waybill = self.make_waybill(waybill_type=False)
        self.add_line(waybill)
        self.assertRefuses(waybill, 'Waybill Type is required')

    def test_start_address_is_required(self):
        waybill = self.make_waybill(start_address=False)
        self.add_line(waybill)
        self.assertRefuses(waybill, 'Start Address is required')

    def test_buyer_tin_required_for_transport_types(self):
        waybill = self.make_waybill(buyer_id=False, buyer_tin=False)
        self.add_line(waybill)
        self.assertRefuses(waybill, 'Buyer TIN is required')

    def test_buyer_cannot_be_our_own_company(self):
        waybill = self.make_waybill(buyer_id=self.env.company.partner_id.id)
        self.add_line(waybill)
        self.assertRefuses(waybill, 'Buyer cannot be your own company')

    def test_own_company_buyer_is_the_waybill_company_not_the_switcher(self):
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'Company B', 'vat': '405000004'})
        self.env.user.company_ids |= company_b
        # B's waybill sold to B, opened with A active: still refused.
        waybill_b = self.make_waybill(company_id=company_b.id, buyer_id=company_b.partner_id.id)
        self.add_line(waybill_b)
        self.assertRefuses(waybill_b.with_context(allowed_company_ids=[company_a.id, company_b.id]),
                           'Buyer cannot be your own company')
        # A's waybill sold to B, opened with B active: a real sale, not refused.
        waybill_a = self.make_waybill(buyer_id=company_b.partner_id.id)
        self.add_line(waybill_a)
        waybill_a.with_context(allowed_company_ids=[company_b.id, company_a.id])._validate_before_save()

    def _switch_medicine(self, waybill, value):
        draft = waybill.new({'is_medicine': value}, origin=waybill)
        return draft, draft._onchange_product_code()

    def test_blank_medicine_set_to_normal_keeps_the_lines(self):
        """A waybill made from a delivery has no Medicine value: picking Normal changes nothing."""
        waybill = self.make_waybill(is_medicine=False)
        self.add_line(waybill)
        draft, result = self._switch_medicine(waybill, '0')
        self.assertEqual(len(draft.line_ids), 1)
        self.assertFalse(result)

    def test_switching_to_medicine_clears_the_lines_and_warns(self):
        waybill = self.make_waybill()
        self.assertEqual(waybill.is_medicine, '0')
        self.add_line(waybill)
        draft, result = self._switch_medicine(waybill, '1')
        self.assertFalse(draft.line_ids)
        self.assertIn('warning', result)

    def test_internal_transport_waives_buyer_but_needs_warehouses(self):
        """Type 1 is a same-company movement: no buyer, but the two warehouses are required."""
        waybill = self.make_waybill(waybill_type='1', buyer_id=False, buyer_tin=False)
        self.add_line(waybill)
        with self.assertRaises(UserError) as e:
            waybill._validate_before_save()
        message = e.exception.args[0]
        self.assertIn('Source Warehouse', message)
        self.assertIn('Destination Warehouse', message)
        self.assertNotIn('Buyer TIN', message)

    def test_without_transport_waives_end_address(self):
        """Type 3 has no transport leg, so no end address / buyer requirement."""
        waybill = self.make_waybill(waybill_type='3', buyer_id=False,
                                    buyer_tin=False, end_address=False)
        self.add_line(waybill)
        waybill._validate_before_save()

    def test_without_transport_needs_no_driver_whatever_rs_echoes(self):
        """RS.GE echoes TRANS_ID=1 (Auto) back on a type 3; its form hides the driver, so none is asked for."""
        waybill = self.make_waybill(waybill_type='3', transport_type='1', driver_tin=False, car_number=False)
        self.add_line(waybill)
        waybill._validate_before_save()

    def test_switching_to_without_transport_clears_the_transport_type(self):
        waybill = self.make_waybill(state='draft')
        self.assertEqual(waybill.transport_type, '1')
        waybill.waybill_type = '3'
        self.assertFalse(waybill.transport_type)
        self.assertFalse(waybill.driver_tin)

    def test_road_transport_requires_driver_and_plate(self):
        waybill = self.make_waybill(driver_tin=False, car_number=False)
        self.add_line(waybill)
        with self.assertRaises(UserError) as e:
            waybill._validate_before_save()
        self.assertIn('Driver TIN is required', e.exception.args[0])
        self.assertIn('Car Number is required', e.exception.args[0])

    def test_foreign_driver_flag_replaces_the_tin(self):
        waybill = self.make_waybill(driver_tin=False, driver_is_foreigner=True)
        self.add_line(waybill)
        waybill._validate_before_save()

    def test_railway_carries_no_driver(self):
        """Only Auto (1), Auto-Foreign (6) and Moped (8) have a driver + plate."""
        waybill = self.make_waybill(transport_type='2', driver_tin=False, car_number=False)
        self.add_line(waybill)
        waybill._validate_before_save()

    def test_errors_are_reported_together(self):
        """One list of everything wrong, not one error at a time."""
        waybill = self.make_waybill(start_address=False, buyer_id=False,
                                    buyer_tin=False, car_number=False)
        with self.assertRaises(UserError) as e:
            waybill._validate_before_save()
        self.assertGreaterEqual(len(e.exception.args[0].splitlines()), 3)


@tagged('post_install', '-at_install')
class TestSubWaybillValidation(RsWaybillCommon):
    """Sub-waybills inherit the parent's driver/transport and validate against its remaining
    quantity."""

    def setUp(self):
        super().setUp()
        self.parent = self.make_waybill(waybill_type='4', rs_internal_id=555)
        self.parent_line = self.add_line(self.parent, quantity=100.0)

    def _make_sub(self, quantity, parent_remaining=100.0, **overrides):
        sub = self.make_waybill(waybill_type='4', parent_waybill_id=self.parent.id,
                                **overrides)
        self.add_line(sub, quantity=quantity, parent_remaining=parent_remaining)
        return sub

    def test_sub_within_available_quantity_passes(self):
        self._make_sub(40.0)._validate_before_save()

    def test_sub_cannot_exceed_parent_remaining(self):
        with self.assertRaises(UserError) as e:
            self._make_sub(140.0)._validate_before_save()
        self.assertIn('exceeds the available', e.exception.args[0])

    def test_sub_line_needs_a_positive_quantity(self):
        """Sub lines start at qty 0; saving one untouched is refused, not sent to RS as a
        zero-quantity good."""
        with self.assertRaises(UserError) as e:
            self._make_sub(0.0)._validate_before_save()
        self.assertIn('greater than 0', e.exception.args[0])

    def test_distribution_sub_needs_its_buyer(self):
        sub = self._make_sub(10.0, buyer_id=False, buyer_tin=False,
                             buyer_name=False, end_address=False)
        with self.assertRaises(UserError) as e:
            sub._validate_before_save()
        message = e.exception.args[0]
        self.assertIn('Buyer TIN is required', message)
        self.assertIn('Delivery Address is required', message)

    def test_internal_sub_needs_warehouses_not_a_buyer(self):
        sub = self.make_waybill(waybill_type='1', parent_waybill_id=self.parent.id,
                                buyer_id=False, buyer_tin=False)
        self.add_line(sub, quantity=10.0, parent_remaining=100.0)
        with self.assertRaises(UserError) as e:
            sub._validate_before_save()
        message = e.exception.args[0]
        self.assertIn('From Warehouse is required', message)
        self.assertIn('To Warehouse is required', message)

    def test_sub_does_not_require_its_own_driver(self):
        """RS auto-fills the sub's driver/transport from the parent."""
        sub = self._make_sub(10.0, driver_tin=False, car_number=False)
        sub._validate_before_save()
