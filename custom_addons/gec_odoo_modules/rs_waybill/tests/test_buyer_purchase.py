"""Vendor waybills and purchase orders (buyer direction). No RS.GE call: Received is simulated by
is_confirmed = '1' plus the receive cascade.
"""

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestBuyerPurchase(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Test Vendor LLC', 'vat': '404040404', 'supplier_rank': 1})
        Product = cls.env['product.product']
        cls.flour = Product.create({'name': 'Flour', 'is_storable': True, 'standard_price': 5.0})
        cls.sugar = Product.create({'name': 'Sugar', 'is_storable': True, 'standard_price': 5.0})
        cls.next_rs_id = 880000

    def vendor_waybill(self, *lines):
        """An active vendor waybill with (product, quantity, price) lines."""
        TestBuyerPurchase.next_rs_id += 1
        return self.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_direction': 'buyer',
            'waybill_type': '2',
            'state': 'active',
            'seller_tin': self.vendor.vat,
            'seller_name': self.vendor.name,
            'rs_internal_id': self.next_rs_id,
            'rs_waybill_number': str(self.next_rs_id),
            'line_ids': [(0, 0, {'product_id': p.id, 'name': p.name, 'quantity': qty,
                                 'unit_price': price}) for p, qty, price in lines],
        })

    def purchase(self, *lines, confirm=True):
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [(0, 0, {'product_id': p.id, 'product_qty': qty, 'price_unit': price})
                           for p, qty, price in lines],
        })
        if confirm:
            po.button_confirm()
        return po

    def link(self, waybill):
        waybill._rs_create_buyer_documents_if_missing()
        return waybill.purchase_id

    def receive(self, waybill):
        waybill.is_confirmed = '1'
        waybill._cascade_validate_receipt()

    def change_goods(self, waybill, vals):
        """The vendor changes the goods on RS.GE; the sync applies it to the waybill."""
        snapshot = waybill._build_line_snapshot()
        waybill.write(vals)
        waybill._apply_rs_goods_diff_auto(snapshot)

    def cancel(self, waybill):
        waybill.state = 'cancelled'
        waybill._cascade_cancel_purchase()

    def line_of(self, po, product):
        return po.order_line.filtered(lambda l: l.product_id == product)

    def test_no_open_po_creates_and_receives(self):
        waybill = self.vendor_waybill((self.flour, 10, 3.0))
        po = self.link(waybill)
        self.assertTrue(waybill.purchase_created)
        self.assertEqual(po.state, 'purchase')
        flour = self.line_of(po, self.flour)
        # The net price is stored with 2 decimals (3 / 1.15 = 2.61): up to 1 tetri off.
        self.assertAlmostEqual(flour.price_total / flour.product_qty, 3.0, delta=0.01,
                               msg="the waybill price has the VAT in it")

        self.receive(waybill)
        self.assertEqual(waybill.picking_id.state, 'done')
        self.assertEqual(self.line_of(po, self.flour).qty_received, 10)
        self.assertEqual(self.flour.qty_available, 10)

    def test_rfq_is_confirmed_and_trucks_share_it(self):
        po = self.purchase((self.flour, 100, 2.0), confirm=False)
        truck1 = self.vendor_waybill((self.flour, 60, 2.0))
        self.assertEqual(self.link(truck1), po)
        self.assertEqual(po.state, 'purchase')
        self.assertFalse(truck1.purchase_created)

        self.receive(truck1)
        self.assertEqual(self.line_of(po, self.flour).qty_received, 60)
        backorder = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        self.assertEqual(len(backorder), 1)

        truck2 = self.vendor_waybill((self.flour, 40, 2.0))
        self.assertEqual(self.link(truck2), po)
        self.receive(truck2)
        self.assertEqual(truck2.picking_id, backorder)
        self.assertEqual(self.line_of(po, self.flour).qty_received, 100)
        self.assertEqual(self.line_of(po, self.flour).product_qty, 100)

    def test_more_than_expected_is_received_on_the_po(self):
        po = self.purchase((self.flour, 100, 2.0))
        truck1 = self.vendor_waybill((self.flour, 60, 2.0))
        self.link(truck1)
        self.receive(truck1)
        truck2 = self.vendor_waybill((self.flour, 50, 2.0))
        self.link(truck2)
        self.receive(truck2)
        self.assertEqual(self.line_of(po, self.flour).qty_received, 110)
        self.assertEqual(self.flour.qty_available, 110)

    def test_po_with_only_some_products_is_not_a_match(self):
        po = self.purchase((self.flour, 10, 2.0))
        waybill = self.vendor_waybill((self.flour, 10, 2.0), (self.sugar, 5, 1.0))
        self.assertNotEqual(self.link(waybill), po)
        self.assertTrue(waybill.purchase_created)

    def test_several_open_pos_ask_the_purchaser(self):
        po1 = self.purchase((self.flour, 100, 2.0))
        po2 = self.purchase((self.flour, 50, 2.0))
        waybill = self.vendor_waybill((self.flour, 50, 2.0))
        self.link(waybill)
        self.link(waybill)
        self.assertFalse(waybill.purchase_id)
        self.assertTrue(waybill.rs_needs_purchase_pick)
        self.assertEqual(waybill.purchase_candidate_ids, po1 | po2)
        self.assertEqual(len(waybill.activity_ids), 1)
        with self.assertRaises(UserError):
            waybill.action_confirm_waybill()

        waybill.purchase_pick_id = po2
        waybill.action_link_purchase()
        self.assertEqual(waybill.purchase_id, po2)
        self.assertFalse(waybill.rs_needs_purchase_pick)
        self.assertFalse(waybill.activity_ids)

    def test_unmapped_line_shows_no_picker_and_link_refuses(self):
        """Sugar not mapped yet: the flour-only PO must not be offered, it is not the order for both."""
        po1 = self.purchase((self.flour, 50, 2.0), confirm=False)
        self.purchase((self.flour, 50, 2.0), (self.sugar, 5, 1.0))
        waybill = self.vendor_waybill((self.flour, 50, 2.0))
        waybill.line_ids = [(0, 0, {'name': 'Sugar (unknown barcode)', 'quantity': 5, 'unit_price': 1.0})]
        self.assertFalse(waybill.rs_needs_purchase_pick)
        self.assertFalse(waybill.purchase_candidate_ids)
        waybill.purchase_pick_id = po1
        with self.assertRaisesRegex(UserError, 'Map the products first'):
            waybill.action_link_purchase()
        self.assertFalse(waybill.purchase_id)
        self.assertEqual(po1.state, 'draft', "the RFQ is not confirmed by a refused link")

    def test_unit_needing_review_shows_no_picker_and_link_refuses(self):
        po1 = self.purchase((self.flour, 100, 2.0))
        self.purchase((self.flour, 50, 2.0))
        waybill = self.vendor_waybill((self.flour, 50, 2.0))
        waybill.line_ids.uom_review = True
        self.assertFalse(waybill.rs_needs_purchase_pick)
        waybill.purchase_pick_id = po1
        with self.assertRaisesRegex(UserError, 'Unit Needs Review'):
            waybill.action_link_purchase()
        self.assertFalse(waybill.purchase_id)

    def test_po_is_created_in_the_waybill_company(self):
        waybill = self.vendor_waybill((self.flour, 3, 1.0))
        self.assertEqual(self.link(waybill).company_id, waybill.company_id)

    def test_vendor_decrease_corrects_the_same_receipt(self):
        waybill = self.vendor_waybill((self.flour, 100, 2.0))
        po = self.link(waybill)
        self.receive(waybill)
        receipt = waybill.picking_id
        outgoing_before = self.env['stock.picking'].search_count(
            [('partner_id', '=', self.vendor.id), ('picking_type_code', '=', 'outgoing')])

        self.change_goods(waybill, {'line_ids': [(1, waybill.line_ids.id, {'quantity': 80})]})
        self.assertTrue(waybill.pending_goods_json)
        self.assertEqual(self.flour.qty_available, 100)
        self.receive(waybill)

        self.assertEqual(waybill.picking_id, receipt)
        self.assertEqual(self.flour.qty_available, 80)
        self.assertEqual(self.line_of(po, self.flour).qty_received, 80)
        self.assertEqual(self.env['stock.picking'].search_count(
            [('partner_id', '=', self.vendor.id), ('picking_type_code', '=', 'outgoing')]),
            outgoing_before)

    def test_vendor_added_product_at_waybill_price(self):
        po = self.purchase((self.flour, 10, 2.0))
        waybill = self.vendor_waybill((self.flour, 10, 2.0))
        self.link(waybill)
        self.receive(waybill)
        self.change_goods(waybill, {'line_ids': [(0, 0, {
            'product_id': self.sugar.id, 'name': self.sugar.name, 'quantity': 4, 'unit_price': 25.0})]})
        self.receive(waybill)

        sugar_line = self.line_of(po, self.sugar)
        self.assertAlmostEqual(sugar_line.price_total / sugar_line.product_qty, 25.0, delta=0.01)
        self.assertEqual(sugar_line.qty_received, 4)
        move = waybill.picking_id.move_ids.filtered(lambda m: m.product_id == self.sugar)
        self.assertEqual(move.state, 'done')
        self.assertTrue(waybill.picking_id.date_done)

    def test_cancel_cancels_a_safe_po_and_a_new_waybill_makes_a_new_one(self):
        po = self.purchase((self.flour, 10, 2.0))
        waybill = self.vendor_waybill((self.flour, 10, 2.0))
        self.link(waybill)
        self.cancel(waybill)
        self.assertEqual(po.state, 'cancel')
        self.assertFalse(po.activity_ids)

        corrected = self.vendor_waybill((self.flour, 10, 2.0))
        new_po = self.link(corrected)
        self.assertNotEqual(new_po, po)
        self.assertTrue(corrected.purchase_created)

    def test_cancel_keeps_a_po_with_received_goods(self):
        po = self.purchase((self.flour, 100, 2.0))
        truck1 = self.vendor_waybill((self.flour, 60, 2.0))
        self.link(truck1)
        self.receive(truck1)
        truck2 = self.vendor_waybill((self.flour, 40, 2.0))
        self.link(truck2)
        self.cancel(truck2)
        self.cancel(truck2)
        self.assertEqual(po.state, 'purchase')
        self.assertFalse(truck2.purchase_id)
        self.assertEqual(len(po.activity_ids), 1)

    def test_cancel_keeps_a_po_with_a_vendor_bill(self):
        po = self.purchase((self.flour, 10, 2.0))
        waybill = self.vendor_waybill((self.flour, 10, 2.0))
        self.link(waybill)
        self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.vendor.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.flour.id, 'quantity': 1, 'price_unit': 2.0,
                                         'purchase_line_id': po.order_line.id})]})
        self.cancel(waybill)
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(len(po.activity_ids), 1)

    def test_cancel_keeps_a_po_another_truck_is_on(self):
        po = self.purchase((self.flour, 100, 2.0))
        truck1 = self.vendor_waybill((self.flour, 50, 2.0))
        truck2 = self.vendor_waybill((self.flour, 50, 2.0))
        self.link(truck1)
        self.link(truck2)
        self.cancel(truck1)
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(truck2.purchase_id, po)

    def test_cancel_after_receipt_changes_nothing(self):
        waybill = self.vendor_waybill((self.flour, 10, 2.0))
        po = self.link(waybill)
        self.receive(waybill)
        self.cancel(waybill)
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(waybill.picking_id.state, 'done')
        self.assertEqual(self.flour.qty_available, 10)
        self.assertEqual(len(po.activity_ids), 1)

    def test_received_waits_for_po_approval(self):
        po = self.purchase((self.flour, 10, 2.0), confirm=False)
        waybill = self.vendor_waybill((self.flour, 10, 2.0))
        self.link(waybill)
        po.state = 'to approve'
        with self.assertRaises(UserError):
            waybill.action_confirm_waybill()

    def _received_then_lowered(self):
        po = self.purchase((self.flour, 100, 2.0))
        truck = self.vendor_waybill((self.flour, 100, 2.0))
        self.link(truck)
        self.receive(truck)
        self.change_goods(truck, {'line_ids': [(1, truck.line_ids.id, {'quantity': 80})]})
        self.receive(truck)
        return po, truck

    def open_receipts(self, po):
        return po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))

    def test_lowered_waybill_asks_whether_the_vendor_still_owes(self):
        po, truck = self._received_then_lowered()

        self.assertEqual(self.flour.qty_available, 80)
        self.assertEqual(self.line_of(po, self.flour).product_qty, 100, "the purchaser decides")
        self.assertTrue(truck.pending_vendor_short_json)
        self.assertIn('20', truck.rs_vendor_short_summary)

        self.receive(truck)
        self.assertTrue(truck.pending_vendor_short_json)

    def test_expect_later_opens_a_receipt_for_the_rest(self):
        po, truck = self._received_then_lowered()

        truck.action_vendor_expect_later()

        self.assertFalse(truck.pending_vendor_short_json)
        self.assertEqual(self.open_receipts(po).move_ids.product_uom_qty, 20)
        truck2 = self.vendor_waybill((self.flour, 20, 2.0))
        self.assertEqual(self.link(truck2), po)
        self.receive(truck2)
        self.assertEqual(self.line_of(po, self.flour).qty_received, 100)

    def test_reduce_the_order_closes_it_at_what_came(self):
        po, truck = self._received_then_lowered()

        truck.action_vendor_reduce_order()

        self.assertFalse(truck.pending_vendor_short_json)
        self.assertEqual(self.line_of(po, self.flour).product_qty, 80)
        self.assertFalse(self.open_receipts(po))

    def test_po_made_from_the_waybill_follows_it_without_asking(self):
        truck = self.vendor_waybill((self.flour, 100, 2.0))
        po = self.link(truck)
        self.receive(truck)
        self.change_goods(truck, {'line_ids': [(1, truck.line_ids.id, {'quantity': 80})]})
        self.receive(truck)

        self.assertEqual(self.line_of(po, self.flour).product_qty, 80)
        self.assertFalse(truck.pending_vendor_short_json)

    def test_raised_again_counts_in_the_po_line_unit(self):
        """Juice is stocked in Units, bought in boxes of 12: what is in question is kept in boxes."""
        units = self.env.ref('uom.product_uom_unit')
        box = self.env['uom.uom'].create({'name': 'Box of 12', 'relative_factor': 12, 'relative_uom_id': units.id})
        juice = self.env['product.product'].create({'name': 'Juice', 'is_storable': True, 'uom_ids': [(6, 0, box.ids)]})
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id, 'order_line': [
            (0, 0, {'product_id': juice.id, 'product_qty': 10, 'uom_id': box.id, 'price_unit': 24.0})]})
        po.button_confirm()
        truck = self.vendor_waybill((juice, 120, 2.0))
        self.assertEqual(self.link(truck), po)
        self.receive(truck)
        line = po.order_line

        for qty, in_question in ((96, {line: 2}), (108, {line: 1}), (120, {})):
            self.change_goods(truck, {'line_ids': [(1, truck.line_ids.id, {'quantity': qty})]})
            self.receive(truck)
            self.assertEqual(truck._rs_vendor_shorts(), in_question, "after %s units" % qty)

    def test_lot_goods_on_a_po_made_from_the_waybill_give_one_todo(self):
        pills = self.env['product.product'].create({'name': 'Paracetamol', 'is_storable': True, 'tracking': 'lot'})
        truck = self.vendor_waybill((pills, 10, 2.0))
        po = self.link(truck)
        self.assertTrue(truck.purchase_created)
        self.receive(truck)
        self.receive(truck)  # the 15-minute repair runs it again

        receipt = truck.picking_id
        self.assertNotEqual(receipt.state, 'done', "lots are entered by hand")
        todos = truck.activity_ids.filtered(lambda a: receipt.name in a.summary)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos.user_id, po.user_id or self.env.user)

    def _two_codes_one_product_received(self):
        """Two vendor codes mapped to Flour (regular and promo) on one waybill; the PO is made from it."""
        truck = self.vendor_waybill((self.flour, 10, 2.0), (self.flour, 5, 1.8))
        po = self.link(truck)
        self.assertTrue(truck.purchase_created)
        self.receive(truck)
        return po, truck

    def po_lines(self, po):
        return [(l.product_qty, l.qty_received) for l in po.order_line.sorted('id')]

    def test_two_codes_of_one_product_are_received_line_by_line(self):
        po, truck = self._two_codes_one_product_received()

        self.assertEqual(self.po_lines(po), [(10, 10), (5, 5)])
        self.assertFalse(self.open_receipts(po), "nothing left waiting")
        self.assertEqual(self.flour.qty_available, 15)

    def test_two_codes_of_one_product_follow_their_own_line_when_changed(self):
        po, truck = self._two_codes_one_product_received()
        regular, promo = truck.line_ids.sorted('id')

        self.change_goods(truck, {'line_ids': [(1, regular.id, {'quantity': 12})]})
        self.receive(truck)
        self.assertEqual(self.po_lines(po), [(12, 12), (5, 5)])

        self.change_goods(truck, {'line_ids': [(1, promo.id, {'quantity': 3})]})
        self.receive(truck)
        self.assertEqual(self.po_lines(po), [(12, 12), (3, 3)])
        self.assertEqual(self.flour.qty_available, 15)
        self.assertFalse(self.open_receipts(po))

    def test_two_codes_of_one_product_added_and_removed_codes(self):
        po, truck = self._two_codes_one_product_received()
        promo = truck.line_ids.sorted('id')[1]

        self.change_goods(truck, {'line_ids': [(0, 0, {'product_id': self.flour.id, 'name': 'Flour X',
                                                        'quantity': 2, 'unit_price': 1.9})]})
        self.receive(truck)
        self.assertEqual(self.po_lines(po), [(10, 10), (5, 5), (2, 2)])

        self.change_goods(truck, {'line_ids': [(2, promo.id)]})
        self.receive(truck)
        self.assertEqual(self.po_lines(po), [(10, 10), (0, 0), (2, 2)],
                         "the promo's own PO line goes to 0; Flour X keeps its line and its price")
        self.assertEqual(po.order_line.sorted('id')[2].price_unit,
                         truck._rs_order_price(1.9, po.order_line.sorted('id')[2]))
        self.assertEqual(self.flour.qty_available, 12)

    def _two_line_po_received(self):
        po = self.purchase((self.flour, 60, 2.0), (self.flour, 40, 2.1))
        truck = self.vendor_waybill((self.flour, 100, 2.0))
        self.assertEqual(self.link(truck), po)
        self.receive(truck)
        line_a, line_b = po.order_line.sorted('id')
        return po, truck, line_a, line_b

    def test_two_po_lines_are_both_received(self):
        po, truck, line_a, line_b = self._two_line_po_received()

        self.assertEqual((line_a.qty_received, line_b.qty_received), (60, 40))
        self.assertFalse(self.open_receipts(po), "all 100 came: no backorder")
        self.assertEqual(self.flour.qty_available, 100)

    def test_two_po_lines_lowered_takes_from_the_last_line(self):
        po, truck, line_a, line_b = self._two_line_po_received()

        self.change_goods(truck, {'line_ids': [(1, truck.line_ids.id, {'quantity': 30})]})
        self.receive(truck)

        self.assertEqual(self.flour.qty_available, 30)
        self.assertEqual((line_a.qty_received, line_b.qty_received), (30, 0))
        self.assertEqual(truck._rs_vendor_shorts(), {line_a: 30, line_b: 40})

        truck.action_vendor_reduce_order()
        self.assertEqual((line_a.product_qty, line_b.product_qty), (30, 0))

    def test_two_po_lines_raised_goes_on_the_last_line(self):
        po, truck, line_a, line_b = self._two_line_po_received()

        self.change_goods(truck, {'line_ids': [(1, truck.line_ids.id, {'quantity': 120})]})
        self.receive(truck)

        self.assertEqual(self.flour.qty_available, 120)
        self.assertEqual((line_a.qty_received, line_b.qty_received), (60, 60))
