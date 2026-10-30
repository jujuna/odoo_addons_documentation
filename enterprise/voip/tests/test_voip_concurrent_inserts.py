from psycopg2 import errorcodes

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import ConcurrencyError
from odoo.tests import TransactionCase, tagged
from odoo.tools import SQL

from odoo.addons.voip.tools.concurrency import expected_unique_violation


@tagged("-at_install", "post_install")
class TestConcurrentInserts(TransactionCase):
    """The browser and the phone-service webhook create the same rows of an
    incoming call milliseconds apart, and an event can be delivered twice: the
    loser of each insert race must be retried (or dropped) without
    ``odoo.sql_db`` logging its failed query as an ERROR.

    Each test plays the race for real: another connection commits the row while
    this transaction is open, so that its snapshot cannot see it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.conversation = cls.env["voip.conversation"].sudo().create({"conversation_identifier": "1792673964.48"})
        cls.call = cls.env["voip.call"].create({
            "user_id": cls.env.user.id,
            "phone_number": "+3225550999",
            "conversation_id": cls.conversation.id,
        })

    def commit_elsewhere(self, table, values):
        """Insert and commit a row from another connection, after this
        transaction's snapshot was taken."""
        self.env.execute_query(SQL("SELECT 1"))  # the snapshot of this transaction exists by now
        self.execute_elsewhere(SQL(
            "INSERT INTO %s (%s) VALUES %s",
            SQL.identifier(table),
            SQL(", ").join(map(SQL.identifier, values)),
            tuple(values.values()),
        ))
        key, value = next(iter(values.items()))
        self.addCleanup(self.delete_elsewhere, table, key, value)

    def delete_elsewhere(self, table, key, value):
        self.execute_elsewhere(SQL("DELETE FROM %s WHERE %s = %s", SQL.identifier(table), SQL.identifier(key), value))

    def execute_elsewhere(self, query):
        with sql_db.db_connect(self.env.cr.dbname).cursor() as other:
            api.Environment(other, SUPERUSER_ID, {}).execute_query(query)
            other.commit()

    def test_the_helper_raises_without_logging(self):
        self.commit_elsewhere("voip_conversation", {"conversation_identifier": "race-helper"})

        with self.assertNoLogs("odoo.sql_db", "ERROR"), self.assertRaises(Exception) as caught, self.env.cr.savepoint():
            with expected_unique_violation():
                self.env["voip.conversation"].sudo().create({"conversation_identifier": "race-helper"})
        self.assertEqual(caught.exception.pgcode, errorcodes.UNIQUE_VIOLATION)

    def test_a_unique_violation_outside_the_helper_is_logged(self):
        self.commit_elsewhere("voip_conversation", {"conversation_identifier": "race-outside"})
        with expected_unique_violation():
            pass

        with self.assertLogs("odoo.sql_db", "ERROR"), self.assertRaises(Exception), self.env.cr.savepoint():
            self.env["voip.conversation"].sudo().create({"conversation_identifier": "race-outside"})

    def test_the_helper_still_logs_other_failed_queries(self):
        with self.assertLogs("odoo.sql_db", "ERROR"), self.assertRaises(Exception), self.env.cr.savepoint():
            with expected_unique_violation():
                self.env.execute_query(SQL("SELECT no_such_column FROM voip_conversation"))

    def test_a_conversation_created_elsewhere_is_retried_quietly(self):
        self.commit_elsewhere("voip_conversation", {"conversation_identifier": "race-conversation"})

        with self.assertNoLogs("odoo.sql_db", "ERROR"), self.assertRaises(ConcurrencyError), self.env.cr.savepoint():
            self.env["voip.conversation"]._get_or_create("race-conversation")

    def test_a_leg_created_elsewhere_is_retried_quietly(self):
        self.commit_elsewhere("voip_call_leg", {"sip_call_id": "race-leg"})

        with self.assertNoLogs("odoo.sql_db", "ERROR"), self.assertRaises(ConcurrencyError), self.env.cr.savepoint():
            self.call._add_sip_call_id("race-leg")

    def test_an_event_delivered_twice_is_dropped_quietly(self):
        self.commit_elsewhere("voip_phone_service_event", {
            "event_id": "race-event", "event_type": "call_created",
        })

        with self.assertNoLogs("odoo.sql_db", "ERROR"):
            event = self.env["voip.phone.service.event"]._register_event(
                "race-event", "call_created", {}, None)

        self.assertFalse(event)
