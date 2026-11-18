"""The goods diff engine used by the Adjustment flow and the RS-driven auto-sync."""

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestLineDiff(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.waybill = self.make_waybill()
        self.other_product = self.env['product.product'].create({
            'name': 'Other Widget',
            'type': 'consu',
        })

    def test_added_line_against_empty_snapshot(self):
        """A waybill with no lines at snapshot time: the added line must be diffed without error."""
        self.waybill.edit_snapshot_json = '[]'
        self.add_line(self.waybill, quantity=7.0)

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]['type'], 'added')
        self.assertEqual(diffs[0]['new_qty'], 7.0)
        self.assertIsNone(diffs[0]['snap'], "an added line has no snapshot counterpart")

    def test_added_line_carries_no_foreign_snapshot(self):
        """With a non-empty snapshot an added line carries no other line's snapshot data."""
        kept = self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        self.add_line(self.waybill, product_id=self.other_product.id, quantity=3.0)

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        added = [d for d in diffs if d['type'] == 'added']
        self.assertEqual(len(added), 1)
        self.assertIsNone(added[0]['snap'])
        self.assertEqual(added[0]['product_id'], self.other_product.id)
        self.assertNotEqual(added[0]['product_id'], kept.product_id.id)

    def test_unchanged_lines_produce_no_diff(self):
        self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        self.assertEqual(self.waybill._compute_line_diff(self.waybill.edit_snapshot_json), [])

    def test_quantity_increase(self):
        line = self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        line.quantity = 8.0

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]['type'], 'qty_up')
        self.assertEqual(diffs[0]['qty_diff'], 3.0)
        self.assertIsNotNone(diffs[0]['snap'])

    def test_quantity_decrease(self):
        line = self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        line.quantity = 2.0

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        self.assertEqual(diffs[0]['type'], 'qty_down')
        self.assertEqual(diffs[0]['qty_diff'], 3.0)

    def test_removed_line(self):
        line = self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        line.unlink()

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]['type'], 'removed')
        self.assertEqual(diffs[0]['old_qty'], 5.0)
        self.assertIsNone(diffs[0]['line'])

    def test_product_swap_splits_into_removed_plus_added(self):
        line = self.add_line(self.waybill, quantity=5.0)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        line.product_id = self.other_product

        diffs = self.waybill._compute_line_diff(self.waybill.edit_snapshot_json)

        types = sorted(d['type'] for d in diffs)
        self.assertEqual(types, ['added', 'removed'])
        added = next(d for d in diffs if d['type'] == 'added')
        removed = next(d for d in diffs if d['type'] == 'removed')
        self.assertEqual(added['product_id'], self.other_product.id)
        self.assertEqual(removed['product_id'], self.product.id)
        self.assertIsNotNone(removed['snap'])

    def test_snapshot_round_trip(self):
        self.add_line(self.waybill, quantity=4.0, unit_price=2.5)
        self.waybill.edit_snapshot_json = self.waybill._build_line_snapshot()
        self.assertEqual(self.waybill._compute_line_diff(self.waybill.edit_snapshot_json), [])
