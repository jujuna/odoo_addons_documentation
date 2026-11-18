"""Distribution stock (#16): the goods leave the warehouse once.

Activating a distribution of 100 moves the 100 from WH/Stock to the warehouse's
Distribution location (the truck). Sub-waybills deliver from the truck, never again from
stock. A remainder made as a Return brings the leftover back to WH/Stock; a remainder made
as a Distribution keeps it on the truck. Cancelling the distribution brings back what is
still on the truck.
"""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDistributionStock(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        patcher = patch.object(self.env.cr, 'commit')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.stock = self.warehouse.lot_stock_id
        self.goods = self.env['product.product'].create({'name': 'Mineral Water', 'is_storable': True})
        self.env['stock.quant']._update_available_quantity(self.goods, self.stock, 100)
        self._rs_id = 992000

    def _waybill(self, qty=100, **vals):
        self._rs_id += 1
        waybill = self.make_waybill(rs_internal_id=self._rs_id, **vals)
        self.add_line(waybill, quantity=qty, product_id=self.goods.id, name=self.goods.name)
        return waybill

    def _distribution(self):
        parent = self._waybill(waybill_type='4', state='active', waybill_status='1', buyer_id=False,
                               source_warehouse_id=self.warehouse.id)
        parent._rs_create_documents_if_missing()
        return parent

    def _sub(self, parent, qty, sub_type='4', **vals):
        self._rs_id += 1
        sub = self.make_waybill(waybill_type=sub_type, parent_waybill_id=parent.id, state='active',
                                waybill_status='1', rs_internal_id=self._rs_id, **vals)
        self.add_line(sub, quantity=qty, product_id=self.goods.id, name=self.goods.name)
        sub._rs_create_documents_if_missing()
        return sub

    def _remainder(self, parent, qty, waybill_type):
        waybill = self._waybill(waybill_type=waybill_type, state='active', waybill_status='1',
                                buyer_id=False, remainder_origin_id=parent.id, qty=qty)
        waybill._rs_create_documents_if_missing()
        return waybill

    def _complete(self, waybill):
        waybill.write({'state': 'completed', 'waybill_status': '2'})
        waybill._do_validate_linked_picking()

    def _on_hand(self, location):
        return self.goods.with_context(location=location.id).qty_available

    @property
    def truck(self):
        return self.warehouse._rs_distribution_location()

    # ── activation ──

    def test_activating_takes_the_goods_out_once(self):
        parent = self._distribution()

        self.assertEqual(parent._rs_truck_take_out().state, 'done')
        self.assertFalse(parent.picking_id, "not its delivery: validating it must not close the "
                                            "distribution on RS.GE")
        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (0, 100))

    def test_activating_again_takes_nothing_more(self):
        parent = self._distribution()
        parent._rs_create_documents_if_missing()

        self.assertEqual(self._on_hand(self.truck), 100)

    def test_a_draft_distribution_takes_nothing(self):
        parent = self._waybill(waybill_type='4', state='draft', waybill_status='0', buyer_id=False)
        parent._rs_create_documents_if_missing()

        self.assertFalse(parent._rs_truck_take_out())
        self.assertEqual(self._on_hand(self.stock), 100)

    def test_each_warehouse_has_one_distribution_location(self):
        self.assertEqual(self.truck, self.warehouse._rs_distribution_location())
        self.assertEqual(self.truck.usage, 'internal')
        self.assertEqual(self.truck.warehouse_id, self.warehouse)

    # ── sub-waybills ──

    def test_a_sub_delivers_from_the_truck(self):
        parent = self._distribution()
        sub = self._sub(parent, 20)

        self.assertEqual(sub.picking_id.location_id, self.truck)
        self._complete(sub)

        self.assertEqual(sub.picking_id.state, 'done')
        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (0, 80))

    def test_an_internal_sub_moves_from_the_truck(self):
        parent = self._distribution()
        other = self.env['stock.warehouse'].create({'name': 'Kutaisi', 'code': 'KTS'})
        sub = self._sub(parent, 30, sub_type='1', buyer_id=False,
                        source_warehouse_id=self.warehouse.id, dest_warehouse_id=other.id)

        self.assertEqual(sub.picking_id.location_id, self.truck)
        self._complete(sub)
        self.assertEqual((self._on_hand(self.truck), self._on_hand(other.lot_stock_id)), (70, 30))

    def test_internal_sub_back_to_the_same_warehouse_still_moves_from_the_truck(self):
        parent = self._distribution()
        sub = self._sub(parent, 30, sub_type='1', buyer_id=False,
                        source_warehouse_id=self.warehouse.id, dest_warehouse_id=self.warehouse.id)
        self.assertEqual((sub.picking_id.location_id, sub.picking_id.location_dest_id), (self.truck, self.stock))

    def test_synced_internal_waybill_to_its_own_warehouse_makes_no_transfer(self):
        """Made on the RS.GE portal: both addresses match the one warehouse, so nothing moves."""
        waybill = self._waybill(waybill_type='1', state='active', waybill_status='1', buyer_id=False,
                                start_address=self.warehouse.name, end_address=self.warehouse.name)
        waybill._rs_create_documents_if_missing()
        self.assertFalse(waybill.picking_id)
        self.assertFalse(self.env['stock.picking'].search([('origin', '=', waybill.rs_waybill_number
                                                            or 'Waybill %s' % waybill.rs_internal_id)]))

    def test_old_distribution_whose_subs_took_from_stock_is_left_alone(self):
        parent = self._waybill(waybill_type='4', state='active', waybill_status='1', buyer_id=False)
        sub = self._sub(parent, 20)
        self.assertEqual(sub.picking_id.location_id, self.stock, "no truck: as before")

        parent._rs_create_documents_if_missing()

        self.assertFalse(parent._rs_truck_take_out(), "its goods were already taken by the subs")

    # ── remainder ──

    def test_a_distribution_remainder_stays_on_the_truck(self):
        parent = self._distribution()
        self._complete(self._sub(parent, 65))

        remainder = self._remainder(parent, 35, '4')

        self.assertFalse(remainder.picking_id)
        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (0, 35))

    def test_the_remainders_own_subs_deliver_from_the_same_truck(self):
        parent = self._distribution()
        self._complete(self._sub(parent, 65))
        remainder = self._remainder(parent, 35, '4')

        self._complete(self._sub(remainder, 10))

        self.assertEqual(self._on_hand(self.truck), 25)

    def test_a_return_remainder_brings_the_leftover_back(self):
        parent = self._distribution()
        self._complete(self._sub(parent, 65))

        remainder = self._remainder(parent, 35, '5')
        self.assertEqual(remainder.picking_id.location_id, self.truck)
        self._complete(remainder)

        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (35, 0))

    # ── cancel ──

    def test_cancelling_brings_back_what_is_still_on_the_truck(self):
        parent = self._distribution()
        delivered = self._sub(parent, 20)
        self._complete(delivered)
        open_sub = self._sub(parent, 30)

        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'ref_waybill_vd', return_value=1):
            parent.action_refuse_waybill()

        self.assertEqual(open_sub.picking_id.state, 'cancel')
        self.assertEqual(delivered.picking_id.state, 'done', "delivered goods stay delivered")
        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (80, 0))

    def test_cancelling_twice_brings_nothing_back_twice(self):
        parent = self._distribution()
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'ref_waybill_vd', return_value=1):
            parent.action_refuse_waybill()
        parent._rs_bring_back_from_truck()

        self.assertEqual((self._on_hand(self.stock), self._on_hand(self.truck)), (100, 0))
