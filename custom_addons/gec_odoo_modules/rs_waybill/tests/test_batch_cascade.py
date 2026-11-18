"""Batch validate / cancel across several waybill-linked transfers: each record is isolated, a
single record stays all-or-nothing.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestBatchCloseCascade(RsWaybillCommon):
    """stock.picking._action_done → waybill.action_close_waybill, per picking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    def _linked_pair(self, rs_id):
        """An active seller waybill with a transfer that ships what it declares, so the quantity
        check passes."""
        waybill = self.make_waybill(state='active', waybill_status='1',
                                    rs_internal_id=rs_id)
        line = self.add_line(waybill)
        location = self.warehouse.lot_stock_id
        location_dest = self.env.ref('stock.stock_location_customers')
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'company_id': self.env.company.id,
            'move_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'uom_id': line.product_id.uom_id.id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
            })],
        })
        picking.move_ids.quantity = line.quantity
        picking.move_ids.picked = True
        picking.waybill_id = waybill.id
        waybill.picking_id = picking.id
        return waybill, picking

    def test_one_failing_close_does_not_stop_the_others(self):
        """Picking 2's RS close fails; pickings 1 and 3 must still be closed."""
        wb1, pick1 = self._linked_pair(830001)
        wb2, pick2 = self._linked_pair(830002)
        wb3, pick3 = self._linked_pair(830003)
        closed = []

        def close(self_wb):
            if self_wb.rs_internal_id == 830002:
                raise UserError("RS.GE rejected the close")
            closed.append(self_wb.rs_internal_id)

        Picking = type(pick1)
        with patch.object(type(wb1), 'action_close_waybill', close), \
             patch.object(Picking, '_action_done',
                          lambda s: super(Picking, s)._action_done()):
            (pick1 | pick2 | pick3)._action_done()

        self.assertEqual(sorted(closed), [830001, 830003])

    def test_the_failure_is_recorded_where_someone_will_see_it(self):
        wb1, pick1 = self._linked_pair(830011)
        wb2, pick2 = self._linked_pair(830012)

        def close(self_wb):
            if self_wb.rs_internal_id == 830012:
                raise UserError("RS.GE rejected the close")

        with patch.object(type(wb1), 'action_close_waybill', close):
            (pick1 | pick2)._action_done()

        self.assertIn('RS.GE rejected the close', wb2.rs_post_commit_error or '',
                      "nothing on the waybill says its RS close never happened")
        self.assertFalse(wb1.rs_post_commit_error,
                         "the waybill that closed fine was flagged too")
        bodies = ' '.join(pick2.message_ids.mapped('body'))
        self.assertIn('could NOT be closed', bodies)

    def test_single_picking_keeps_all_or_nothing(self):
        """One transfer, one waybill: the RS error must reach the caller and roll back super()'s
        work."""
        wb, pick = self._linked_pair(830021)

        with patch.object(type(wb), 'action_close_waybill',
                          side_effect=UserError("RS.GE rejected the close")):
            with self.assertRaises(UserError):
                pick._action_done()

    def test_buyer_direction_is_never_closed_from_here(self):
        """RS rejects closing a vendor's waybill; the buyer lifecycle uses Receive/Reject."""
        wb, pick = self._linked_pair(830031)
        wb.waybill_direction = 'buyer'

        with patch.object(type(wb), 'action_close_waybill') as close:
            pick._action_done()

        close.assert_not_called()


@tagged('post_install', '-at_install')
class TestBatchCancelCascade(RsWaybillCommon):
    """stock.picking.action_cancel → waybill delete/refuse, per picking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    def _linked_pair(self, rs_id, state='active'):
        waybill = self.make_waybill(state=state, waybill_status='1', rs_internal_id=rs_id)
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'company_id': self.env.company.id,
        })
        picking.waybill_id = waybill.id
        waybill.picking_id = picking.id
        return waybill, picking

    def test_a_picking_whose_rs_cancel_failed_is_not_cancelled(self):
        """If the RS cancel fails, the waybill stays active on RS and its picking stays live in
        Odoo."""
        wb1, pick1 = self._linked_pair(840001)
        wb2, pick2 = self._linked_pair(840002)

        def refuse(self_wb):
            if self_wb.rs_internal_id == 840002:
                raise UserError("RS.GE refused the cancel")
            self_wb.state = 'cancelled'

        with patch.object(type(wb1), 'action_refuse_waybill', refuse):
            (pick1 | pick2).action_cancel()

        self.assertEqual(pick1.state, 'cancel', "the healthy picking should be cancelled")
        self.assertNotEqual(pick2.state, 'cancel',
                            "the picking whose waybill is still live on RS was cancelled anyway")

    def test_the_blocked_picking_reports_why(self):
        wb1, pick1 = self._linked_pair(840011)
        wb2, pick2 = self._linked_pair(840012)

        def refuse(self_wb):
            if self_wb.rs_internal_id == 840012:
                raise UserError("RS.GE refused the cancel")
            self_wb.state = 'cancelled'

        with patch.object(type(wb1), 'action_refuse_waybill', refuse):
            (pick1 | pick2).action_cancel()

        bodies = ' '.join(pick2.message_ids.mapped('body'))
        self.assertIn('NOT cancelled', bodies)
        self.assertIn('RS.GE refused the cancel', wb2.rs_post_commit_error or '')

    def test_single_picking_still_aborts_the_whole_cancel(self):
        wb, pick = self._linked_pair(840021)

        with patch.object(type(wb), 'action_refuse_waybill',
                          side_effect=UserError("RS.GE refused the cancel")):
            with self.assertRaises(UserError):
                pick.action_cancel()

        self.assertNotEqual(pick.state, 'cancel')

    def test_already_cancelled_waybills_are_skipped(self):
        wb, pick = self._linked_pair(840031, state='cancelled')

        with patch.object(type(wb), 'action_refuse_waybill') as refuse:
            pick.action_cancel()

        refuse.assert_not_called()
        self.assertEqual(pick.state, 'cancel')
