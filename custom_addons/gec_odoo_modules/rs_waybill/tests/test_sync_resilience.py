"""One bad row, chunk or company must not sink the whole sync run."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestPerCompanyIsolation(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({'vat': '400888111'})
        cls.clear_rs_responsible(cls.env.company)
        cls.company_b = cls.env['res.company'].create({
            'name': 'Resilience Second Co', 'vat': '400888222'})
        for login, company in (('rs_res_a', cls.env.company), ('rs_res_b', cls.company_b)):
            user = cls.env['res.users'].create({
                'name': login, 'login': login,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
            })
            user.with_company(company).write({'rs_username': '%s_rs' % login, 'rs_password': 'secret',
                                              'rs_is_responsible': True})
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Resilience Plain', 'login': 'rs_res_plain',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def setUp(self):
        super().setUp()
        # rollback is stubbed on the instance: TransactionCase forbids a real one.
        patcher = patch.object(self.env.cr, 'rollback')
        self.rollback = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_broken_company_does_not_stop_the_others(self):
        """The first company's RS.GE account being down must not stop the second company."""
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        reached = []

        def one_pass(scoped):
            reached.append(scoped.env.company)
            if scoped.env.company == self.env.company:
                raise ValueError("RS.GE is down for this account")
            return (1, 0, 0)

        with patch.object(type(Waybill), '_sync_seller_waybills_one', one_pass):
            Waybill.action_sync_seller_waybills()

        self.assertIn(self.company_b, reached,
                      "the healthy company was never reached")

    def test_totals_still_add_up_when_one_company_fails(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)

        def one_pass(scoped):
            if scoped.env.company == self.env.company:
                raise ValueError("boom")
            return (3, 2, 1)

        with patch.object(type(Waybill), '_sync_seller_waybills_one', one_pass):
            result = Waybill.action_sync_seller_waybills()

        self.assertIn('3', str(result))

    def test_the_failed_pass_is_rolled_back_before_the_next_one_starts(self):
        """The failed pass is rolled back before the next company starts, so a DB error cannot kill
        every later query."""
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)

        def one_pass(scoped):
            if scoped.env.company == self.env.company:
                raise ValueError("boom")
            return (0, 0, 0)

        with patch.object(type(Waybill), '_sync_seller_waybills_one', one_pass):
            Waybill.action_sync_seller_waybills()

        self.rollback.assert_called_once()

    def test_a_healthy_run_never_rolls_anything_back(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        with patch.object(type(Waybill), '_sync_seller_waybills_one',
                          lambda scoped: (0, 0, 0)):
            Waybill.action_sync_seller_waybills()
        self.rollback.assert_not_called()

    def test_drift_repair_isolates_companies_too(self):
        Waybill = self.env['rs.waybill'].with_user(self.plain_user).with_context(cron_id=1)
        reached = []

        def one_pass(scoped):
            reached.append(scoped.env.company)
            if len(reached) == 1:
                raise ValueError("boom")

        with patch.object(type(Waybill), '_cron_rs_drift_repair_one', one_pass):
            Waybill._cron_rs_drift_repair()

        self.assertEqual(len(reached), 2)


@tagged('post_install', '-at_install')
class TestChunkedFetchResilience(RsWaybillCommon):
    """_fetch_waybills_chunked: a failed window must not discard the good ones."""

    def test_a_failing_window_keeps_the_rows_already_fetched(self):
        calls = {'n': 0}

        def fetch_fn(start_date=None, end_date=None, **kwargs):
            calls['n'] += 1
            if calls['n'] == 2:
                raise ValueError("RS.GE fault on this window")
            return [{'ID': '%s' % calls['n']}]

        rows = self.env['rs.waybill']._fetch_waybills_chunked(
            fetch_fn, days_back=9, chunk_days=3)

        self.assertGreater(calls['n'], 2, "the fetch stopped at the failing window")
        self.assertTrue(rows, "every row was discarded because one window failed")
        self.assertNotIn('2', [r['ID'] for r in rows])

    def test_duplicate_ids_across_windows_are_collapsed(self):
        def fetch_fn(start_date=None, end_date=None, **kwargs):
            return [{'ID': '77'}]

        rows = self.env['rs.waybill']._fetch_waybills_chunked(
            fetch_fn, days_back=9, chunk_days=3)

        self.assertEqual(len(rows), 1)


@tagged('post_install', '-at_install')
class TestTransporterFetchResilience(RsWaybillCommon):

    def test_a_failed_fetch_does_not_take_down_the_cron(self):
        Service = type(self.env['rs.waybill.soap.service'])
        with patch.object(Service, 'get_transporter_waybills',
                          side_effect=ValueError("RS.GE fault")):
            self.assertEqual(
                self.env['rs.waybill']._sync_transporter_waybills_one(), (0, 0, 0))
