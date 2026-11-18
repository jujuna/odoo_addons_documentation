import csv
import io

from odoo.tests import tagged

from .common import DAY, HotelRmsCommon


@tagged('post_install', '-at_install')
class TestDecisions(HotelRmsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hotel._run_engine()
        cls.price = cls.env['hotel.rms.price'].search([
            ('property_id', '=', cls.hotel.id), ('stay_date', '=', cls.today + 2 * DAY),
            ('room_type_id', '=', cls.double.id)])

    def _audit(self, price=None):
        return (price or self.price).audit_ids.sorted('id')

    def _live(self, rate=180):
        """Sets both rates the way a rates import does."""
        self.price.write({'published_rate': rate, 'exported_rate': rate})

    def test_accept_publishes_the_recommendation(self):
        price = self.price.with_user(self.manager)
        recommended = price.recommended_rate
        price.action_accept()
        self.assertEqual((price.state, price.published_rate), ('accepted', recommended))
        self.assertEqual(price.decided_by, self.manager)
        self.assertTrue(price.decided_at)
        self.assertTrue(price.to_export)

    def test_accept_writes_an_audit_row_with_the_user_and_the_rates(self):
        self._live(180)
        self.price.with_user(self.manager).action_accept()
        audit = self._audit()
        self.assertEqual(len(audit), 1)
        self.assertEqual((audit.action, audit.user_id), ('accept', self.manager))
        self.assertEqual((audit.old_rate, audit.new_rate), (180, self.price.recommended_rate))
        self.assertEqual(audit.recommended_rate, self.price.recommended_rate)

    def test_accepting_many_prices_writes_one_audit_row_each(self):
        prices = self._price(3) + self._price(4)
        prices.with_user(self.manager).action_accept()
        self.assertEqual(prices.mapped('state'), ['accepted', 'accepted'])
        self.assertEqual(len(prices.audit_ids), 2)

    def test_accept_skips_locked_rows_and_rows_without_a_recommendation(self):
        locked = self._price(3)
        locked.action_lock()
        empty = self._price(4)
        empty.recommended_rate = 0
        (locked + empty).action_accept()
        self.assertEqual((locked.state, empty.state), ('pending', 'pending'))
        self.assertEqual(locked.published_rate, 0)

    def test_use_my_price_publishes_the_manager_price(self):
        price = self.price.with_user(self.manager)
        price.decided_rate = 217
        price.action_use_my_price()
        self.assertEqual((price.state, price.published_rate), ('edited', 217))
        self.assertEqual(self._audit().action, 'edit')

    def test_using_the_same_price_twice_keeps_undo_working(self):
        self._live(180)
        self.price.decided_rate = 217
        self.price.action_use_my_price()
        self.price.action_use_my_price()
        self.assertEqual(self._audit().mapped('action'), ['edit'])
        self.price.action_undo()
        self.assertEqual(self.price.published_rate, 180)

    def test_the_note_of_a_repeated_own_price_is_dropped(self):
        self._live(180)
        self.price.decided_rate = 217
        self.price.action_use_my_price()
        self.price.note = "again"
        self.price.action_use_my_price()
        self.assertFalse(self.price.note)
        self.assertEqual(self._audit().mapped('action'), ['edit'])

    def test_use_my_price_without_a_price_changes_nothing(self):
        self.price.action_use_my_price()
        self.assertEqual((self.price.state, self.price.published_rate), ('pending', 0))
        self.assertFalse(self._audit())

    def test_quick_price_is_rounded_to_the_step_inside_the_season(self):
        self.hotel.price_step = 5
        self.price.recommended_rate = 203
        self.price.action_quick_price(pct=10)
        self.assertEqual((self.price.state, self.price.published_rate), ('edited', 225))

    def test_quick_price_reads_the_percent_from_the_context(self):
        self.hotel.price_step = 5
        self.price.recommended_rate = 203
        self.price.with_context(quick_pct=-10).action_quick_price()
        self.assertEqual(self.price.published_rate, 185)

    def test_quick_price_never_leaves_the_season_range(self):
        self.hotel.price_step = 5
        self.price.recommended_rate = 390
        self.price.action_quick_price(pct=10)
        self.assertEqual(self.price.published_rate, 400)

    def test_reject_drops_an_accepted_price_that_was_not_exported(self):
        self._live(180)
        self.price.action_accept()
        self.price.action_reject()
        self.assertEqual((self.price.state, self.price.published_rate), ('rejected', 180))
        self.assertFalse(self.price.to_export)
        audit = self._audit()[-1]
        self.assertEqual((audit.action, audit.new_rate), ('reject', 180))

    def test_reject_keeps_the_published_price_of_a_pending_row(self):
        self._live(180)
        self.price.action_reject()
        self.assertEqual((self.price.state, self.price.published_rate), ('rejected', 180))

    def test_undo_restores_the_price_before_an_accept(self):
        self._live(180)
        self.price.action_accept()
        self.assertTrue(self.price.can_undo)
        self.price.action_undo()
        self.assertEqual((self.price.state, self.price.published_rate), ('pending', 180))
        self.assertFalse(self.price.decided_by)
        self.assertEqual(self._audit()[-1].action, 'undo')

    def test_undo_only_reverts_the_newest_decision(self):
        self._live(180)
        self.price.action_accept()
        accepted = self.price.published_rate
        self.price.decided_rate = 230
        self.price.action_use_my_price()
        self.price.action_undo()
        self.assertEqual(self.price.published_rate, accepted)
        self.assertFalse(self.price.can_undo)
        self.price.action_undo()
        self.assertEqual(self.price.published_rate, accepted)
        self.assertEqual(self._audit().mapped('action'), ['accept', 'edit', 'undo'])

    def test_undo_is_not_offered_after_another_action_follows(self):
        self.price.action_accept()
        self.price.action_lock()
        self.assertFalse(self.price.can_undo)
        self.price.action_undo()
        self.assertEqual(self.price.state, 'accepted')

    def test_undo_is_not_offered_once_the_price_matches_the_export(self):
        self.price.write({'exported_rate': self.price.recommended_rate})
        self.price.action_accept()
        self.assertFalse(self.price.to_export)
        self.assertFalse(self.price.can_undo)

    def test_undo_is_not_offered_after_the_export(self):
        self.price.action_accept()
        self.hotel.action_publish_approved()
        self.assertFalse(self.price.can_undo)

    def test_the_dashboard_counts_the_decisions_of_the_month(self):
        self.price.action_accept()
        edited = self._price(3)
        edited.decided_rate = 230
        edited.action_use_my_price()
        self._price(4).action_reject()
        self.assertEqual(self.hotel.decision_split, {'accepted': 1, 'edited': 1, 'rejected': 1})

    def test_the_panel_offers_undo_to_a_manager_only_while_it_is_possible(self):
        self.price.action_accept()
        self.assertTrue(self.price.with_user(self.manager).get_panel_data()['actions']['undo'])
        self.assertFalse(self.price.with_user(self.viewer).get_panel_data()['actions']['undo'])
        self.price.action_lock()
        self.assertFalse(self.price.with_user(self.manager).get_panel_data()['actions']['undo'])

    def test_undo_of_a_rejection_restores_the_state_only(self):
        self._live(180)
        self.price.action_reject()
        self.assertTrue(self.price.can_undo)
        self.price.action_undo()
        self.assertEqual((self.price.state, self.price.published_rate), ('pending', 180))

    def test_lock_and_unlock_are_audited(self):
        self.price.action_lock()
        self.assertTrue(self.price.locked)
        self.price.action_unlock()
        self.assertFalse(self.price.locked)
        self.assertEqual(self._audit().mapped('action'), ['lock', 'unlock'])

    def test_locked_rows_cannot_be_decided(self):
        self.price.action_lock()
        self.price.decided_rate = 230
        self.price.action_use_my_price()
        self.price.action_reject()
        self.assertEqual((self.price.state, self.price.published_rate), ('pending', 0))

    def test_the_engine_does_not_change_a_locked_row(self):
        self.price.action_lock()
        recommended, run = self.price.recommended_rate, self.price.run_id
        self.season.base_rate = 300
        new_run = self._run()
        self.assertEqual((self.price.recommended_rate, self.price.run_id), (recommended, run))
        self.assertGreater(self._price(3).recommended_rate, recommended)
        self.assertEqual(self._price(3).run_id, new_run)

    def test_the_engine_does_not_rewrite_a_row_decided_today(self):
        self.price.action_accept()
        recommended = self.price.recommended_rate
        self.season.base_rate = 300
        self._run()
        self.assertEqual(self.price.recommended_rate, recommended)
        self.assertGreater(self._price(3).recommended_rate, recommended)

    def test_a_row_decided_on_an_earlier_day_is_recomputed(self):
        self.price.action_accept()
        self.price.decided_at = self.price.decided_at - 2 * DAY
        recommended = self.price.recommended_rate
        self.season.base_rate = 300
        self._run()
        self.assertGreater(self.price.recommended_rate, recommended)

    def test_export_writes_a_csv_marks_the_prices_and_is_audited(self):
        self._live(180)
        self.price.action_accept()
        other = self._price(3, self.suite)
        other.decided_rate = 333
        other.action_use_my_price()
        action = self.hotel.with_user(self.manager).action_publish_approved()
        attachment = self.env['ir.attachment'].search([('res_model', '=', 'hotel.rms.property'),
                                                       ('res_id', '=', self.hotel.id)])
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn(str(attachment.id), action['url'])
        rows = list(csv.reader(io.StringIO(attachment.raw.content.decode())))
        self.assertEqual(rows[0], ['date', 'room_type', 'price'])
        self.assertEqual(sorted(rows[1:]), sorted([
            [str(self.price.stay_date), 'DBL', str(self.price.recommended_rate)],
            [str(other.stay_date), 'STE', '333.0'],
        ]))
        self.assertFalse(self.price.to_export or other.to_export)
        self.assertEqual((self.price.exported_rate, other.exported_rate), (self.price.recommended_rate, 333))
        export = self._audit()[-1]
        self.assertEqual((export.action, export.old_rate, export.new_rate), ('export', 180, self.price.recommended_rate))

    def test_export_with_nothing_to_publish_writes_only_the_header(self):
        self.hotel.action_publish_approved()
        attachment = self.env['ir.attachment'].search([('res_model', '=', 'hotel.rms.property'),
                                                       ('res_id', '=', self.hotel.id)])
        self.assertEqual(attachment.raw.content.decode().split(), ['date,room_type,price'])
        self.assertFalse(self.env['hotel.rms.price.audit'].search([('property_id', '=', self.hotel.id)]))
