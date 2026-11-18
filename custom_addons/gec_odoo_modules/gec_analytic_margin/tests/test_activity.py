from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import GecMarginCommon


@tagged('post_install', '-at_install')
class TestActivityMeasurement(GecMarginCommon):

    def test_hours_are_measured_per_target_account(self):
        self._drivers()
        activity = self._activity()
        quantities = activity.get_quantities(self.date_from, self.date_to)
        self.assertEqual(quantities.get(self.bl_a.id), 70.0)
        self.assertEqual(quantities.get(self.bl_b.id), 30.0)

    def test_missing_filter_counts_invoice_quantities(self):
        """With no filter the activity sums unit_amount on every line of the plan, invoice quantities included."""
        self._drivers()
        self._line(amount=-500.0, quantity=1.0, target=self.bl_a,
                   gl=self.gl_pool, name='T bill line')

        unfiltered = self._activity(source_domain='[]')
        self.assertEqual(unfiltered.get_quantities(self.date_from, self.date_to)[self.bl_a.id],
                         71.0, "unfiltered measurement should pick up the bill line")

        filtered = self._activity(source_domain="[('general_account_id', '=', False)]")
        self.assertEqual(filtered.get_quantities(self.date_from, self.date_to)[self.bl_a.id],
                         70.0, "the filter must exclude journal-generated lines")

    def test_count_measure_ignores_quantity(self):
        self._drivers(a=70.0, b=30.0)
        activity = self._activity(measure='count', measure_field=False)
        quantities = activity.get_quantities(self.date_from, self.date_to)
        self.assertEqual(quantities[self.bl_a.id], 1.0)
        self.assertEqual(quantities[self.bl_b.id], 1.0)

    def test_period_is_respected(self):
        self._drivers()
        self._line(quantity=999.0, target=self.bl_a, name='T out of period')\
            .write({'date': '2026-01-15'})
        activity = self._activity()
        quantities = activity.get_quantities(self.date_from, self.date_to)
        self.assertEqual(quantities[self.bl_a.id], 70.0)

    def test_bad_path_is_reported_not_swallowed(self):
        self._drivers()
        activity = self._activity(source_analytic_path='no_such_field')
        with self.assertRaises(UserError):
            activity.get_quantities(self.date_from, self.date_to)

    def test_path_must_lead_to_an_analytic_account(self):
        self._drivers()
        activity = self._activity(source_analytic_path='company_id')
        with self.assertRaises(UserError):
            activity.get_quantities(self.date_from, self.date_to)

    def test_rate_uses_the_whole_pool_not_the_charged_part(self):
        """Capacity reduces what is charged out, never the cost of one unit."""
        self._drivers()
        activity = self._activity(practical_capacity=200.0)
        rate = activity.get_rate(40000.0, self.date_from, self.date_to)
        self.assertEqual(rate, 200.0, "40,000 over 200 hours of capacity is 200/hour")
