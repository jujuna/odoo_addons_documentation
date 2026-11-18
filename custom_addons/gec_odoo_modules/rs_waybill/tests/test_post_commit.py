"""After an irreversible RS.GE call is committed, a failing post-commit step must not escape as a traceback,
must be recorded on the waybill, and must be retried by the drift job."""

from unittest.mock import Mock, patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestPostCommitHelper(RsWaybillCommon):
    """_rs_post_commit itself: the contract every wrapped step relies on."""

    def setUp(self):
        super().setUp()
        self.waybill = self.make_waybill()

    def test_successful_step_reports_true_and_leaves_no_flag(self):
        ran = []
        result = self.waybill._rs_post_commit('Do the thing', lambda: ran.append(1))
        self.assertTrue(result)
        self.assertEqual(ran, [1])
        self.assertFalse(self.waybill.rs_post_commit_error)

    def test_failing_step_does_not_raise(self):
        def boom():
            raise ValueError("stock is missing")
        result = self.waybill._rs_post_commit('Validate the linked transfer', boom)
        self.assertFalse(result)

    def test_failing_step_is_recorded_on_the_record(self):
        def boom():
            raise ValueError("stock is missing")
        self.waybill._rs_post_commit('Validate the linked transfer', boom)
        self.assertIn('Validate the linked transfer', self.waybill.rs_post_commit_error)
        self.assertIn('stock is missing', self.waybill.rs_post_commit_error)

    def test_failing_step_posts_to_chatter(self):
        before = len(self.waybill.message_ids)
        self.waybill._rs_post_commit('Validate the linked transfer',
                                     Mock(side_effect=ValueError("nope")))
        self.assertGreater(len(self.waybill.message_ids), before)

    def test_partial_work_is_rolled_back_to_the_savepoint(self):
        """A step that half-succeeded leaves nothing behind, so the retry does not trip over it."""
        def half_then_fail():
            self.waybill.comment = 'partial work'
            raise ValueError("failed after writing")

        self.waybill._rs_post_commit('Half a step', half_then_fail)

        self.assertNotEqual(self.waybill.comment, 'partial work',
                            "the partial write survived the failed step")

    def test_transaction_is_still_usable_after_a_database_error(self):
        """The savepoint keeps the transaction usable after a DB error, so the failure can still be
        recorded."""
        def bad_sql():
            self.env.cr.execute("SELECT * FROM a_table_that_does_not_exist")

        self.waybill._rs_post_commit('Touch a missing table', bad_sql)

        # Without the savepoint this query would raise InternalError (transaction aborted).
        self.assertTrue(self.env['rs.waybill'].search_count([('id', '=', self.waybill.id)]))
        self.assertIn('Touch a missing table', self.waybill.rs_post_commit_error)


@tagged('post_install', '-at_install')
class TestPostCommitRepair(RsWaybillCommon):
    """_rs_repair_local_state: the part that makes a failure temporary."""

    def setUp(self):
        super().setUp()
        self.env.company.rs_stock_integration_date = '2020-01-01'
        self.warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    def _completed_waybill_with_open_picking(self):
        """A seller waybill RS considers delivered, whose transfer never moved (what a failed
        post-commit cascade leaves)."""
        waybill = self.make_waybill(state='completed', waybill_status='2',
                                    rs_internal_id=700001,
                                    activation_date='2026-01-01 08:00:00')
        self.add_line(waybill)
        picking = self.env['stock.picking'].with_context(skip_rs_auto_create=True).create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'company_id': self.env.company.id,
        })
        waybill.picking_id = picking.id
        return waybill, picking

    def test_repair_retries_a_transfer_that_never_validated(self):
        waybill, picking = self._completed_waybill_with_open_picking()
        waybill.rs_post_commit_error = 'Validate the linked transfer: boom'

        with patch.object(type(waybill), '_cascade_validate_picking') as cascade:
            waybill._rs_repair_local_state()

        cascade.assert_called_once()

    def test_repair_is_a_no_op_once_the_transfer_is_done(self):
        waybill, picking = self._completed_waybill_with_open_picking()

        with patch.object(type(picking), 'state', 'done'), \
             patch.object(type(waybill), '_cascade_validate_picking') as cascade:
            waybill._rs_repair_local_state()

        cascade.assert_not_called()

    def test_repair_skips_cancelled_waybills(self):
        waybill, _picking = self._completed_waybill_with_open_picking()
        waybill.state = 'cancelled'

        with patch.object(type(waybill), '_cascade_validate_picking') as cascade:
            waybill._rs_repair_local_state()

        cascade.assert_not_called()

    def test_flag_clears_once_nothing_is_outstanding(self):
        waybill, picking = self._completed_waybill_with_open_picking()
        waybill.rs_post_commit_error = 'Validate the linked transfer: boom'
        # The retry resolves the transfer; a bare picking can only reach cancel, not 'done'.
        picking.action_cancel()

        waybill._rs_repair_local_state()

        self.assertFalse(waybill.rs_post_commit_error,
                         "the flag should clear once the step finally goes through")

    def test_flag_survives_a_retry_that_fails_again(self):
        waybill, picking = self._completed_waybill_with_open_picking()

        with patch.object(type(waybill), '_cascade_validate_picking',
                          side_effect=ValueError("still no stock")):
            waybill._rs_repair_local_state()

        self.assertIn('still no stock', waybill.rs_post_commit_error)

    def test_a_transfer_that_keeps_failing_is_reported_once_and_not_counted_repaired(self):
        """The drift job runs every 15 minutes: one chatter message and the banner, not one per run."""
        waybill, picking = self._completed_waybill_with_open_picking()
        notes = lambda: waybill.message_ids.filtered(lambda m: picking.name in (m.body or ''))

        results = [waybill._rs_repair_local_state() for _run in range(3)]

        self.assertEqual(len(notes()), 1)
        self.assertIn(picking.name, waybill.rs_post_commit_error)
        self.assertEqual(results, [False, False, False])

    def test_buyer_receipt_is_repaired_on_its_own_condition(self):
        waybill, _picking = self._completed_waybill_with_open_picking()
        waybill.write({'waybill_direction': 'buyer', 'is_confirmed': '1',
                       'state': 'active'})

        with patch.object(type(waybill), '_cascade_validate_receipt') as receipt, \
             patch.object(type(waybill), '_cascade_validate_picking') as delivery:
            waybill._rs_repair_local_state()

        receipt.assert_called_once()
        delivery.assert_not_called()

    def test_outstanding_detection_matches_what_repair_acts_on(self):
        waybill, picking = self._completed_waybill_with_open_picking()
        self.assertTrue(waybill._rs_has_outstanding_step())
        waybill.state = 'cancelled'
        self.assertFalse(waybill._rs_has_outstanding_step())


@tagged('post_install', '-at_install')
class TestCloseLifecycleSurvivesCascadeFailure(RsWaybillCommon):
    """End to end: Complete a waybill whose transfer refuses to validate."""

    def setUp(self):
        super().setUp()
        self.waybill = self.make_waybill(state='active', waybill_status='1',
                                         rs_internal_id=700002,
                                         transport_start_date='2026-01-01 08:00:00',
                                         delivery_date='2026-01-01 10:00:00')
        self.add_line(self.waybill)

    def test_close_completes_locally_even_when_the_cascade_blows_up(self):
        """RS accepted the close, so the waybill must end up completed in Odoo despite the cascade
        failure."""
        Service = type(self.env['rs.waybill.soap.service'])
        Waybill = type(self.waybill)
        with patch.object(Waybill, '_rs_create_documents_if_missing'), \
             patch.object(Waybill, '_close_on_rs'), \
             patch.object(Service, 'get_full_waybill', return_value=(None, [])), \
             patch.object(Waybill, '_send_notification_email'), \
             patch.object(Waybill, '_cascade_validate_picking',
                          side_effect=ValueError("not enough stock")), \
             patch.object(self.env.cr, 'commit'):
            # cr.commit is patched on the instance: TransactionCase installs a forbidden commit there.
            # No assertRaises: a raised exception here is the bug.
            self.waybill.action_close_waybill()

        self.assertEqual(self.waybill.state, 'completed')
        self.assertIn('not enough stock', self.waybill.rs_post_commit_error or '',
                      "the failed cascade left no trace on the record")
