# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPreparationTimeReport(TestPoSCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config

    def _create_order_line_for_report(self, utc_datetime='2024-06-15 10:30:00', preparation_time=120):
        product = self.create_product('Prep Product', self.categ_basic, 10)
        self.config.open_ui()
        order = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': self.config.current_session_id.id,
            'partner_id': self.partner_a.id,
            'lines': [Command.create({
                'name': 'Prep line',
                'product_id': product.id,
                'price_unit': 10,
                'qty': 1,
                'price_subtotal': 10,
                'price_subtotal_incl': 10,
            })],
            'amount_paid': 10.0,
            'amount_total': 10.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        self.env.flush_all()
        line = order.lines[0]
        self.env.cr.execute(
            """
                UPDATE pos_order_line
                   SET preparation_time = %s,
                       create_date = %s
                 WHERE id = %s
            """,
            (preparation_time, utc_datetime, line.id),
        )
        self.env['preparation.time.report'].invalidate_model()
        return line

    def test_order_hour_follows_current_user_timezone(self):
        """The report must bucket lines using the viewing user's timezone.

        With the old static SQL view, the timezone was frozen when init() ran
        as superuser (OdooBot) during module upgrade. Changing the user
        timezone afterwards had no effect on order_hour.
        """
        line = self._create_order_line_for_report()
        user = self.env.user
        user_tz = user.tz

        try:
            user.write({'tz': 'Europe/Brussels'})
            report = self.env['preparation.time.report']
            record = report.search([('id', '=', line.id)])
            self.assertEqual(record.order_hour, '12:00')

            user.write({'tz': 'America/New_York'})
            report.invalidate_model()
            record = report.search([('id', '=', line.id)])
            self.assertEqual(record.order_hour, '06:00')
        finally:
            user.write({'tz': user_tz})

    def test_init_does_not_persist_static_sql_view(self):
        """init() must not recreate a PostgreSQL view with a frozen timezone."""
        self.env['preparation.time.report'].init()
        self.env.cr.execute("""
            SELECT EXISTS (
                SELECT 1
                  FROM pg_views
                 WHERE viewname = 'preparation_time_report'
            )
        """)
        self.assertFalse(self.env.cr.fetchone()[0])

    def test_average_preparation_time(self):
        """Create multiple orders to test average preparation time calculation"""

        # Create multiple pos orders
        product = self.create_product('Prep Product', self.categ_basic, 10)
        self.config.open_ui()
        order_1 = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': self.config.current_session_id.id,
            'partner_id': self.partner_a.id,
            'lines': [Command.create({
                'name': 'Prep line',
                'product_id': product.id,
                'price_unit': 10,
                'qty': 1,
                'price_subtotal': 10,
                'price_subtotal_incl': 10,
            })],
            'amount_paid': 10.0,
            'amount_total': 10.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        order_2 = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': self.config.current_session_id.id,
            'partner_id': self.partner_a.id,
            'lines': [Command.create({
                'name': 'Prep line',
                'product_id': product.id,
                'price_unit': 10,
                'qty': 1,
                'price_subtotal': 10,
                'price_subtotal_incl': 10,
            })],
            'amount_paid': 10.0,
            'amount_total': 10.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        self.env.flush_all()

        # Modify line information for calculation
        line_1 = order_1.lines[0]
        line_2 = order_2.lines[0]
        preparation_time_1 = 10
        preparation_time_2 = 20
        utc_datetime_1 = '2024-06-15 10:30:00'
        utc_datetime_2 = '2024-04-15 10:30:00'
        query = """
                UPDATE pos_order_line
                   SET preparation_time = %s,
                       create_date = %s
                 WHERE id = %s
            """
        self.env.cr.execute(query, (preparation_time_1, utc_datetime_1, line_1.id))
        self.env.cr.execute(query, (preparation_time_2, utc_datetime_2, line_2.id))

        # Calculate average using same method used via the front-end
        total_averages = self.env['preparation.time.report']._read_group([], ('order_hour', 'pos_config_id'), ('__count', 'avg_preparation_time:avg'))
        line_1_averages = self.env['preparation.time.report']._read_group([("create_date", "<", '2024-05-15 10:30:00')], ('order_hour', 'pos_config_id'), ('__count', 'avg_preparation_time:avg'))

        self.assertEqual(total_averages[0][3], 15.0)
        self.assertEqual(line_1_averages[0][3], 20.0)
