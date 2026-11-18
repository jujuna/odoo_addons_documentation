"""Per-company RS settings: the stock switch, cutoffs and notification recipients live on the company."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestPerCompanySettings(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Settings Second Co'})

    def test_each_company_keeps_its_own_integration_date(self):
        self.company_a.rs_stock_integration_date = '2026-01-01'
        self.company_b.rs_stock_integration_date = '2026-06-01'
        self.assertNotEqual(self.company_a.rs_stock_integration_date,
                            self.company_b.rs_stock_integration_date)

    def test_scope_follows_the_waybills_own_company(self):
        """A waybill of company B is judged against company B's go-live date, not company A's."""
        (self.company_a | self.company_b).rs_enable_stock = True
        self.company_a.rs_stock_integration_date = '2026-01-01'
        self.company_b.rs_stock_integration_date = '2026-06-01'

        wb_a = self.make_waybill(company_id=self.company_a.id,
                                 activation_date='2026-03-01 09:00:00')
        wb_b = self.make_waybill(company_id=self.company_b.id,
                                 activation_date='2026-03-01 09:00:00')

        self.assertTrue(wb_a._in_integration_scope(),
                        "March is after company A's January go-live")
        self.assertFalse(wb_b._in_integration_scope(),
                         "March is before company B's June go-live — company A's date leaked")

    def test_mapping_cutoff_follows_the_waybills_own_company(self):
        self.company_a.rs_mapping_cutoff_date = '2026-01-01'
        self.company_b.rs_mapping_cutoff_date = '2026-06-01'

        wb_a = self.make_waybill(company_id=self.company_a.id)
        wb_b = self.make_waybill(company_id=self.company_b.id)
        self.force_create_date(wb_a, '2026-03-01 09:00:00')
        self.force_create_date(wb_b, '2026-03-01 09:00:00')

        self.assertTrue(wb_a._mapping_enabled())
        self.assertFalse(wb_b._mapping_enabled())

    def test_unset_cutoff_still_means_disabled(self):
        self.company_b.rs_stock_integration_date = False
        wb = self.make_waybill(company_id=self.company_b.id,
                               activation_date='2026-03-01 09:00:00')
        self.assertFalse(wb._in_integration_scope())

    def test_notification_recipients_are_per_company(self):
        user_a = self.env['res.users'].create({
            'name': 'Notify A', 'login': 'rs_notify_a',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        user_b = self.env['res.users'].create({
            'name': 'Notify B', 'login': 'rs_notify_b',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self.company_a.rs_notification_user_ids = [(6, 0, [user_a.id])]
        self.company_b.rs_notification_user_ids = [(6, 0, [user_b.id])]

        wb_b = self.make_waybill(company_id=self.company_b.id)

        self.assertEqual(wb_b._get_notification_users(), user_b)

    def test_recipient_lookup_no_longer_parses_a_string(self):
        """A Many2many recipient list cannot fail on a stray character the way a comma-separated
        string did."""
        self.company_a.rs_notification_user_ids = [(5, 0, 0)]
        self.assertEqual(self.make_waybill()._get_notification_users(),
                         self.env['res.users'])

    def test_settings_dialog_writes_through_to_the_company(self):
        """The settings fields are related=, so the standard machinery persists them to the company."""
        settings = self.env['res.config.settings'].create({
            'rs_enable_stock': True,
            'rs_stock_integration_date': '2026-09-09',
            'rs_mapping_cutoff_date': '2026-09-10',
        })
        settings.execute()
        self.assertTrue(self.env.company.rs_enable_stock)
        self.assertEqual(str(self.env.company.rs_stock_integration_date), '2026-09-09')
        self.assertEqual(str(self.env.company.rs_mapping_cutoff_date), '2026-09-10')
