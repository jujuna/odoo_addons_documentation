"""The columns that waybill screens, syncs and stock look up by are indexed."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestIndexes(TransactionCase):

    def _indexdefs(self, table):
        self.env.cr.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        return [row[0] for row in self.env.cr.fetchall()]

    def test_lookup_columns_are_indexed(self):
        for table, column in [('rs_waybill_line', 'rs_waybill_id'),
                              ('stock_picking', 'waybill_id'),
                              ('rs_waybill', 'picking_id'),
                              ('rs_waybill', 'purchase_id'),
                              ('rs_waybill', 'sales_order_id'),
                              ('rs_waybill', 'company_id')]:
            with self.subTest(table=table, column=column):
                self.assertTrue(any('(%s)' % column in d for d in self._indexdefs(table)),
                                "%s.%s has no index" % (table, column))

    def test_list_sort_is_indexed(self):
        self.assertTrue(any('create_date DESC' in d for d in self._indexdefs('rs_waybill')))
