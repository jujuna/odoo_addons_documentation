"""A user starts the sync only for their own companies; an administrator and the scheduled jobs
reach all.
"""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSyncCompanyScope(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_a.vat = self.company_a.vat or '206322102'
        self.company_b = self.env['res.company'].create({'name': 'Company B', 'vat': '405000001'})
        self.clerk = self.env['res.users'].create({
            'name': 'Clerk A', 'login': 'clerk_a', 'company_id': self.company_a.id,
            'company_ids': [(6, 0, self.company_a.ids)],
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)]})
        patcher = patch.object(type(self.env['rs.waybill']), '_get_rs_sync_user',
                               lambda self, company=None: self.env.user)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _companies(self, env):
        return {company for company, _user in env['rs.waybill']._rs_sync_contexts()}

    def test_a_normal_user_reaches_only_their_companies(self):
        companies = self._companies(self.env(user=self.clerk))
        self.assertIn(self.company_a, companies)
        self.assertNotIn(self.company_b, companies)

    def test_an_administrator_reaches_every_company(self):
        self.assertIn(self.company_b, self._companies(self.env(user=self.env.ref('base.user_admin'))))

    def test_the_scheduled_job_reaches_every_company(self):
        cron_env = self.env(user=self.clerk, context=dict(self.env.context, cron_id=1))
        self.assertIn(self.company_b, self._companies(cron_env))
