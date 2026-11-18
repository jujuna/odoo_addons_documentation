"""Adjustment history snapshot: goods and transport cost are marked against RS.GE's current version."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestAdjustmentSnapshot(RsWaybillCommon):

    def _good(self, code, name, qty, price='5'):
        return {'BAR_CODE': code, 'W_NAME': name, 'QUANTITY': str(qty), 'PRICE': price,
                'AMOUNT': str(float(qty) * float(price)), 'UNIT_TXT': 'ც', 'VAT_TYPE': '0'}

    def _snapshot(self, old, current, old_header=None, current_header=None):
        waybill = self.make_waybill(rs_internal_id=970001)
        wizard = self.env['rs.waybill.adjustment.wizard'].create({
            'waybill_id': waybill.id, 'line_ids': [(0, 0, {'archival_id': 55, 'user_name': 'u'})]})
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, 'get_adjusted_waybill', return_value=(old_header or {'STATUS': '1'}, old)), \
                patch.object(Service, 'get_full_waybill', return_value=(current_header or {'STATUS': '1'}, current)):
            action = wizard.line_ids.action_view_snapshot()
        return self.env['rs.waybill.adjustment.snapshot'].browse(action['res_id'])

    def test_goods_marked_against_the_current_version(self):
        snapshot = self._snapshot(
            old=[self._good('A', 'Milk', 10), self._good('B', 'Bread', 5), self._good('C', 'Salt', 1)],
            current=[self._good('A', 'Milk', 8), self._good('B', 'Bread', 5), self._good('D', 'Sugar', 2)])

        self.assertEqual([(line.name, line.status) for line in snapshot.line_ids],
                         [('Milk', 'changed'), ('Bread', 'same'), ('Salt', 'removed'), ('Sugar', 'added')])
        self.assertEqual(snapshot.line_ids[0].quantity, 10, "the old version's quantity is shown")

    def test_same_product_twice_is_compared_row_by_row(self):
        snapshot = self._snapshot(
            old=[self._good('A', 'Milk', 10), self._good('A', 'Milk', 3)],
            current=[self._good('A', 'Milk', 10)])

        self.assertEqual(snapshot.line_ids.mapped('status'), ['same', 'removed'])

    def test_rounding_is_not_a_change(self):
        snapshot = self._snapshot(
            old=[self._good('A', 'Milk', '10.00000000001')], current=[self._good('A', 'Milk', 10)],
            old_header={'TRANSPORT_COAST': '100.00000000001'}, current_header={'TRANSPORT_COAST': '100'})

        self.assertEqual(snapshot.line_ids.status, 'same')
        self.assertNotIn('transport_cost', snapshot.drift_field_names or '')

    def test_a_real_cost_change_is_still_marked(self):
        snapshot = self._snapshot(old=[], current=[],
                                  old_header={'TRANSPORT_COAST': '100'}, current_header={'TRANSPORT_COAST': '250'})

        self.assertIn('transport_cost', snapshot.drift_field_names)

    def test_no_current_version_no_marks(self):
        waybill = self.make_waybill(rs_internal_id=970002)
        wizard = self.env['rs.waybill.adjustment.wizard'].create({
            'waybill_id': waybill.id, 'line_ids': [(0, 0, {'archival_id': 56})]})
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, 'get_adjusted_waybill', return_value=({'STATUS': '1'}, [self._good('A', 'Milk', 1)])), \
                patch.object(Service, 'get_full_waybill', return_value=(None, [])):
            action = wizard.line_ids.action_view_snapshot()
        snapshot = self.env['rs.waybill.adjustment.snapshot'].browse(action['res_id'])

        self.assertFalse(snapshot.line_ids.status)
        self.assertFalse(snapshot.drift_field_names)
