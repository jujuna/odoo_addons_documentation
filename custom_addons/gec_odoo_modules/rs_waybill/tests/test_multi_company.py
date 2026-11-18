"""Multi-company isolation on waybills. The RS crons run as ONE credentialed user and must still sweep every company:
a narrowed search would miss an existing waybill and the unique index on rs_internal_id would reject it."""

from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestWaybillCompanyIsolation(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Second Company'})

        cls.user_a = cls.env['res.users'].create({
            'name': 'User A', 'login': 'rs_user_a',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.both_user = cls.env['res.users'].create({
            'name': 'User AB', 'login': 'rs_user_ab',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id, cls.company_b.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

        cls.wb_a = cls.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_type': '2', 'company_id': cls.company_a.id,
            'start_address': 'A', 'rs_internal_id': 810001,
        })
        cls.wb_b = cls.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_type': '2', 'company_id': cls.company_b.id,
            'start_address': 'B', 'rs_internal_id': 810002,
        })

    def test_user_sees_only_their_own_companys_waybills(self):
        visible = self.env['rs.waybill'].with_user(self.user_a).search(
            [('rs_internal_id', 'in', [810001, 810002])])
        self.assertIn(self.wb_a, visible)
        self.assertNotIn(self.wb_b, visible, "company B's waybill leaked to a company A user")

    def test_reading_another_companys_waybill_is_refused(self):
        with self.assertRaises(AccessError):
            self.wb_b.with_user(self.user_a).read(['start_address'])

    def test_writing_another_companys_waybill_is_refused(self):
        with self.assertRaises(AccessError):
            self.wb_b.with_user(self.user_a).write({'comment': 'not mine'})

    def test_user_of_both_companies_sees_both(self):
        visible = self.env['rs.waybill'].with_user(self.both_user).with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]).search(
            [('rs_internal_id', 'in', [810001, 810002])])
        self.assertIn(self.wb_a, visible)
        self.assertIn(self.wb_b, visible)

    def test_goods_lines_follow_their_waybill(self):
        """Lines have no company_id; without a rule of their own they would expose another company's
        data."""
        line_b = self.env['rs.waybill.line'].create({
            'rs_waybill_id': self.wb_b.id, 'product_id': self.product.id,
            'quantity': 5.0, 'unit_price': 99.0,
        })
        visible = self.env['rs.waybill.line'].with_user(self.user_a).search(
            [('rs_waybill_id', 'in', [self.wb_a.id, self.wb_b.id])])
        self.assertNotIn(line_b, visible, "company B's goods line leaked")


@tagged('post_install', '-at_install')
class TestCronsStillSpanCompanies(RsWaybillCommon):
    """The rule must not narrow the background sync, which runs as ONE user."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({'name': 'Cron Second Company'})
        cls.wb_a = cls.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_type': '2', 'company_id': cls.env.company.id,
            'start_address': 'A', 'rs_internal_id': 820001,
        })
        cls.wb_b = cls.env['rs.waybill'].with_context(rs_skip_resolve=True).create({
            'waybill_type': '2', 'company_id': cls.company_b.id,
            'start_address': 'B', 'rs_internal_id': 820002,
        })
        cls.single_company_user = cls.env['res.users'].create({
            'name': 'Cron User', 'login': 'rs_cron_user',
            'company_id': cls.env.company.id,
            'company_ids': [(6, 0, [cls.env.company.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_existing_record_lookup_crosses_companies(self):
        """_process_rs_rows resolves RS ids against all held waybills; a miss makes a known waybill
        look new."""
        as_cron = self.env['rs.waybill'].with_user(self.single_company_user)
        found = as_cron.sudo().search([('rs_internal_id', 'in', [820001, 820002])])
        self.assertIn(self.wb_a, found)
        self.assertIn(self.wb_b, found,
                      "the cron lost sight of the other company's waybill")

    def test_without_sudo_the_cron_would_be_narrowed(self):
        """Pins down why the sudo above is required; if this stops being true, the sudo can go."""
        as_cron = self.env['rs.waybill'].with_user(self.single_company_user)
        found = as_cron.search([('rs_internal_id', 'in', [820001, 820002])])
        self.assertIn(self.wb_a, found)
        self.assertNotIn(self.wb_b, found)
