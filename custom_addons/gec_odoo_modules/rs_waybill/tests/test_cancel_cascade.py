"""A cancelled seller waybill ends the sale: the open delivery is cancelled and the sales order is
cancelled or reduced; a done delivery is never touched.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestCancelCascade(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self._rs_id = 800000

    def _order(self, qty=10.0):
        order = self.env['sale.order'].create({
            'partner_id': self.buyer.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': qty})],
        })
        order.with_context(skip_rs_auto_create=True).action_confirm()
        return order

    def _ship(self, picking, qty):
        """Validate `qty` of the picking; the rest goes to a backorder."""
        move = picking.move_ids
        move.quantity = qty
        move.picked = True
        picking.with_context(skip_rs_auto_create=True)._action_done()
        return picking.backorder_ids

    def _cancelled_waybill(self, order, picking):
        self._rs_id += 1
        waybill = self.make_waybill(state='cancelled', waybill_status='-2',
                                    rs_internal_id=self._rs_id,
                                    sales_order_id=order.id, picking_id=picking.id)
        self.add_line(waybill, quantity=sum(picking.move_ids.mapped('product_uom_qty')))
        return waybill

    def _activities(self, record):
        return self.env['mail.activity'].search(
            [('res_model', '=', record._name), ('res_id', '=', record.id)])

    def test_nothing_shipped_cancels_the_whole_order(self):
        order = self._order()
        picking = order.picking_ids
        waybill = self._cancelled_waybill(order, picking)

        waybill._cascade_cancel_delivery()

        self.assertEqual(picking.state, 'cancel')
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(waybill.rs_cancel_cascade, 'done')

    def test_cancelled_backorder_reduces_the_order_to_what_was_delivered(self):
        order = self._order()
        backorder = self._ship(order.picking_ids, 4)
        waybill = self._cancelled_waybill(order, backorder)

        waybill._cascade_cancel_delivery()

        line = order.order_line
        self.assertEqual(backorder.state, 'cancel')
        self.assertEqual(order.state, 'sale', "part of it was delivered: the order stays")
        self.assertEqual(line.product_uom_qty, 4)
        self.assertEqual(line.qty_delivered, 4)
        self.assertFalse(order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')),
                         "reducing the order must not procure a new delivery")

    def test_done_delivery_is_left_alone_and_flagged(self):
        order = self._order()
        picking = order.picking_ids
        self._ship(picking, 10)
        waybill = self._cancelled_waybill(order, picking)

        waybill._cascade_cancel_delivery()
        waybill._cascade_cancel_delivery()

        self.assertEqual(picking.state, 'done')
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.order_line.product_uom_qty, 10)
        self.assertEqual(len(self._activities(waybill)), 1)

    def test_locked_order_is_not_changed_but_flagged(self):
        order = self._order()
        backorder = self._ship(order.picking_ids, 4)
        order.action_lock()
        waybill = self._cancelled_waybill(order, backorder)

        waybill._cascade_cancel_delivery()

        self.assertEqual(backorder.state, 'cancel')
        self.assertEqual(order.order_line.product_uom_qty, 10)
        self.assertEqual(len(self._activities(order)), 1)

    def test_invoiced_order_is_reduced_and_asks_for_a_credit_note(self):
        if not self.env['account.journal'].search(
                [('type', '=', 'sale'), ('company_id', '=', self.env.company.id)], limit=1):
            self.skipTest("no sales journal in this database")
        self.product.invoice_policy = 'order'
        order = self._order()
        invoice = order._create_invoices()
        invoice.action_post()
        waybill = self._cancelled_waybill(order, order.picking_ids)

        waybill._cascade_cancel_delivery()

        self.assertEqual(order.state, 'sale', "an invoiced order is never cancelled here")
        self.assertEqual(order.order_line.product_uom_qty, 0)
        self.assertEqual(invoice.state, 'posted', "the invoice itself is not touched")
        self.assertEqual(len(self._activities(order)), 1)

    def test_buyer_waybill_is_not_touched(self):
        order = self._order()
        picking = order.picking_ids
        waybill = self._cancelled_waybill(order, picking)
        waybill.waybill_direction = 'buyer'

        waybill._cascade_cancel_delivery()

        self.assertEqual(picking.state, 'assigned')
        self.assertFalse(waybill.rs_cancel_cascade)

    def test_failed_follow_up_is_rolled_back_and_retried(self):
        order = self._order()
        picking = order.picking_ids
        waybill = self._cancelled_waybill(order, picking)

        with patch.object(type(waybill), '_rs_cancel_reduce_order',
                          side_effect=ValueError("boom")):
            waybill._cascade_cancel_delivery()

        self.assertEqual(waybill.rs_cancel_cascade, 'pending')
        self.assertIn('boom', waybill.rs_post_commit_error)
        self.assertEqual(picking.state, 'assigned', "the half-done cancel was rolled back")
        self.assertTrue(waybill._rs_has_outstanding_step())

        self.assertTrue(waybill._rs_repair_local_state())

        self.assertEqual(picking.state, 'cancel')
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(waybill.rs_cancel_cascade, 'done')
        self.assertFalse(waybill.rs_post_commit_error)
        self.assertFalse(waybill._rs_has_outstanding_step())

    def test_waybills_cancelled_before_this_change_are_not_retried(self):
        order = self._order()
        waybill = self._cancelled_waybill(order, order.picking_ids)

        self.assertFalse(waybill._rs_has_outstanding_step())
        self.assertFalse(waybill._rs_repair_local_state())
        self.assertEqual(order.state, 'sale')

    def _cancel_in_odoo(self, waybill):
        """The Cancel button with RS.GE accepting; returns the follow-up flag as it stood at commit."""
        seen = []
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'refuse_waybill', return_value=1), \
                patch.object(self.env.cr, 'commit',
                             side_effect=lambda: seen.append(waybill.rs_cancel_cascade)):
            waybill.action_refuse_waybill()
        return seen[0]

    def _active_waybill(self, order, picking):
        self._rs_id += 1
        waybill = self.make_waybill(state='active', waybill_status='1', rs_internal_id=self._rs_id,
                                    sales_order_id=order.id, picking_id=picking.id)
        self.add_line(waybill, quantity=sum(picking.move_ids.mapped('product_uom_qty')))
        return waybill

    def test_pending_is_saved_with_the_cancel(self):
        order = self._order()
        picking = order.picking_ids
        waybill = self._active_waybill(order, picking)

        flag_at_commit = self._cancel_in_odoo(waybill)

        self.assertEqual(flag_at_commit, 'pending',
                         "a stop right after the commit must leave something the drift job retries")
        self.assertEqual(picking.state, 'cancel')
        self.assertEqual(waybill.rs_cancel_cascade, 'done')

    def test_done_delivery_gets_no_pending(self):
        order = self._order()
        picking = order.picking_ids
        self._ship(picking, 10)
        waybill = self._active_waybill(order, picking)

        flag_at_commit = self._cancel_in_odoo(waybill)

        self.assertFalse(flag_at_commit)
        self.assertEqual(len(self._activities(waybill)), 1, "goods left: one activity, as before")

    def _two_open_deliveries(self):
        order = self._order()
        first = order.picking_ids
        first.move_ids.quantity = 4
        first.with_context(skip_rs_auto_create=True).action_split_transfer()
        second = order.picking_ids - first
        waybills = self.env['rs.waybill']
        for picking in first | second:
            waybill = self._active_waybill(order, picking)
            picking.waybill_id = waybill
            waybills |= waybill
        return order, first, second, waybills

    def _cancel_order(self, order, error_for=()):
        def refuse(rs_id):
            if rs_id in error_for:
                raise UserError("RS.GE could not be reached")
            return 1
        service = type(self.env['rs.waybill.soap.service'])
        with patch.object(service, 'refuse_waybill', side_effect=refuse), \
                patch.object(self.env.cr, 'commit'):
            order._action_cancel()

    def test_order_cancel_stops_on_an_rs_error_and_can_be_retried(self):
        order, first, second, (w1, w2) = self._two_open_deliveries()

        with self.assertRaisesRegex(UserError, 'could not be reached'):
            self._cancel_order(order, error_for={w2.rs_internal_id})

        # assertRaises rolls back here; on a server the first delivery's cancel is already committed.
        self.assertEqual(order.state, 'sale', "a live delivery keeps the order alive")
        self.assertEqual(w2.state, 'active')
        self.assertNotEqual(second.state, 'cancel')

        self._cancel_order(order)

        self.assertEqual(order.state, 'cancel')
        self.assertEqual((first.state, second.state), ('cancel', 'cancel'))
        self.assertEqual((w1.state, w2.state), ('cancelled', 'cancelled'))

    def test_batch_cancel_without_order_still_skips_the_failing_one(self):
        order, first, second, (w1, w2) = self._two_open_deliveries()
        service = type(self.env['rs.waybill.soap.service'])

        def refuse(rs_id):
            if rs_id == w2.rs_internal_id:
                raise UserError("RS.GE could not be reached")
            return 1
        with patch.object(service, 'refuse_waybill', side_effect=refuse), \
                patch.object(self.env.cr, 'commit'):
            (first | second).action_cancel()

        self.assertEqual(first.state, 'cancel')
        self.assertNotEqual(second.state, 'cancel')
