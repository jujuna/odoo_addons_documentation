"""RS.GE account per sync pass: an account belongs to ONE taxpayer, so each company is synced under its own
RS Responsible User; an operator with own credentials runs exactly one pass."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestSyncContexts(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_a.write({'vat': '400111111'})
        cls.clear_rs_responsible(cls.company_a)
        cls.company_b = cls.env['res.company'].create({
            'name': 'Sync Second Co', 'vat': '400222222'})
        cls.company_no_tin = cls.env['res.company'].create({'name': 'No TIN Co'})

        cls.user_a = cls._make_credentialed_user('rs_sync_a', cls.company_a)
        cls.user_b = cls._make_credentialed_user('rs_sync_b', cls.company_b)
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Plain', 'login': 'rs_sync_plain',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    @classmethod
    def _make_credentialed_user(cls, login, company, responsible=True):
        user = cls.env['res.users'].create({
            'name': login, 'login': login,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        # Logins are stored per company: write them under the company they serve.
        user.with_company(company).write({'rs_username': '%s_rs' % login, 'rs_password': 'secret',
                                          'rs_is_responsible': responsible})
        return user

    def _contexts_as(self, user):
        return self.env['rs.waybill'].with_user(user).with_context(cron_id=1)._rs_sync_contexts()

    def test_each_company_gets_its_own_account(self):
        """Each company syncs under its own account; one borrowed account only sees its own
        taxpayer's waybills."""
        contexts = dict(self._contexts_as(self.plain_user))
        self.assertIn(self.company_a, contexts)
        self.assertIn(self.company_b, contexts)
        self.assertEqual(contexts[self.company_a], self.user_a)
        self.assertEqual(contexts[self.company_b], self.user_b)

    def test_a_company_with_no_credentials_is_skipped_not_borrowed_from(self):
        company_c = self.env['res.company'].create({
            'name': 'Uncredentialed Co', 'vat': '400333333'})
        contexts = dict(self._contexts_as(self.plain_user))
        self.assertNotIn(company_c, contexts,
                         "a company with no RS account must be skipped, not synced "
                         "through somebody else's credentials")

    def test_a_company_with_no_tin_is_not_an_rs_taxpayer(self):
        contexts = dict(self._contexts_as(self.plain_user))
        self.assertNotIn(self.company_no_tin, contexts)

    def test_interactive_user_runs_exactly_one_pass_as_themselves(self):
        """Fetch All clicked by a credentialed operator runs one pass as themselves."""
        contexts = self.env['rs.waybill'].with_user(self.user_b).with_company(
            self.company_b)._rs_sync_contexts()
        self.assertEqual(contexts, [(self.company_b, self.user_b)])

    def test_a_login_without_the_responsible_flag_is_not_used(self):
        company_d = self.env['res.company'].create({
            'name': 'Login Only Co', 'vat': '400444555'})
        login_only = self._make_credentialed_user('rs_sync_login_only', company_d, responsible=False)
        self.assertFalse(self.env['rs.waybill']._get_rs_sync_user(company=company_d),
                         "a login without the RS Responsible flag must not run the crons")
        login_only.with_company(company_d).write({'rs_is_responsible': True})
        self.assertEqual(self.env['rs.waybill']._get_rs_sync_user(company=company_d), login_only)

    def test_lookup_needs_a_login_stored_for_that_company(self):
        company_d = self.env['res.company'].create({
            'name': 'Access Only Co', 'vat': '400444444'})
        shared = self.env['res.users'].create({
            'name': 'Multi Admin', 'login': 'rs_sync_multi',
            'company_id': self.company_a.id,
            'company_ids': [(6, 0, [self.company_a.id, company_d.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        shared.with_company(self.company_a).write({'rs_username': 'multi_rs', 'rs_password': 'secret'})
        self.assertFalse(self.env['rs.waybill']._get_rs_sync_user(company=company_d),
                         "a login stored for company A does not serve company D")
        shared.with_company(company_d).write({'rs_username': 'multi_rs', 'rs_password': 'secret',
                                              'rs_is_responsible': True})
        self.assertEqual(
            self.env['rs.waybill']._get_rs_sync_user(company=company_d), shared)


@tagged('post_install', '-at_install')
class TestSyncRunsPerCompany(RsWaybillCommon):
    """The entry points loop over companies, under the right credentials each time."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({'vat': '400555555'})
        cls.clear_rs_responsible(cls.env.company)
        cls.company_b = cls.env['res.company'].create({
            'name': 'Loop Second Co', 'vat': '400666666'})
        for login, company in (('rs_loop_a', cls.env.company), ('rs_loop_b', cls.company_b)):
            user = cls.env['res.users'].create({
                'name': login, 'login': login,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
            })
            user.with_company(company).write({'rs_username': '%s_rs' % login, 'rs_password': 'secret',
                                              'rs_is_responsible': True})
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Loop Plain', 'login': 'rs_loop_plain',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def test_seller_sync_runs_once_per_company(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        seen = []

        def one_pass(wb_self):
            seen.append((wb_self.env.company, wb_self.env.user.rs_username))
            return (0, 0, 0)

        with patch.object(type(Waybill), '_sync_seller_waybills_one', one_pass):
            Waybill.action_sync_seller_waybills()

        companies = [c for c, _u in seen]
        self.assertEqual(len(seen), 2, "only one company was synced")
        self.assertIn(self.env.company, companies)
        self.assertIn(self.company_b, companies)

    def test_each_pass_uses_that_companys_credentials(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        seen = {}

        def one_pass(wb_self):
            seen[wb_self.env.company] = wb_self.env.user.rs_username
            return (0, 0, 0)

        with patch.object(type(Waybill), '_sync_seller_waybills_one', one_pass):
            Waybill.action_sync_seller_waybills()

        self.assertEqual(seen[self.env.company], 'rs_loop_a_rs')
        self.assertEqual(seen[self.company_b], 'rs_loop_b_rs',
                         "company B was fetched with the wrong account")

    def test_drift_repair_runs_per_company(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        seen = []

        def one_pass(wb_self):
            seen.append(wb_self.env.company)

        with patch.object(type(Waybill), '_cron_rs_drift_repair_one', one_pass):
            Waybill._cron_rs_drift_repair()

        self.assertEqual(len(seen), 2)


@tagged('post_install', '-at_install')
class TestPerCompanySyncCursor(RsWaybillCommon):
    """last_v1_sync is per company; a shared one would skip a window the other company never
    fetched."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({
            'name': 'Cursor Second Co', 'vat': '400777777'})

    def test_each_company_has_its_own_key(self):
        Waybill = self.env['rs.waybill']
        self.assertNotEqual(Waybill._rs_last_sync_key(self.env.company),
                            Waybill._rs_last_sync_key(self.company_b))

    def test_legacy_shared_cursor_is_honoured_once(self):
        """An upgraded database resumes where it left off instead of re-fetching 30 days per
        company."""
        ICP = self.env['ir.config_parameter'].sudo()
        Waybill = self.env['rs.waybill']
        ICP.set_str(Waybill._rs_last_sync_key(self.env.company), False)
        ICP.set_str('rs_waybill.last_v1_sync', '2026-08-01T00:00:00')

        self.assertEqual(Waybill._rs_get_last_sync(self.env.company),
                         '2026-08-01T00:00:00')

    def test_a_companys_own_cursor_wins_over_the_legacy_one(self):
        ICP = self.env['ir.config_parameter'].sudo()
        Waybill = self.env['rs.waybill']
        ICP.set_str('rs_waybill.last_v1_sync', '2026-08-01T00:00:00')
        ICP.set_str(Waybill._rs_last_sync_key(self.company_b), '2026-08-10T00:00:00')

        self.assertEqual(Waybill._rs_get_last_sync(self.company_b),
                         '2026-08-10T00:00:00')
