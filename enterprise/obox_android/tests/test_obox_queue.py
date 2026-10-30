from unittest.mock import patch

from odoo.exceptions import UserError

from odoo.addons.obox.tests.common import CommonOboxTest
from odoo.addons.obox_android.models.obox_queue import _UNIQUE_ANDROID_ACTION_TYPES


class TestOboxAndroidQueue(CommonOboxTest):
    def _pending(self, action_type):
        return self.env["obox.queue"].search([
            ("obox_id", "=", self.obox.id),
            ("action_type", "=", action_type),
            ("status", "=", "pending"),
        ])

    def test_reloading_the_kiosk_queues_the_command(self):
        self.obox.action_kiosk_reload()

        self.assertEqual(len(self._pending("kiosk_reload")), 1)
        self.assertEqual(
            self._pending("kiosk_reload").payload["url"], "/odoo/kiosk_reload",
        )

    def test_a_kiosk_action_is_unique_per_box(self):
        self.obox.action_kiosk_reload()

        with self.assertRaises(UserError):
            self.obox.action_kiosk_reload()

    def test_every_android_unique_action_is_refused_while_one_is_waiting(self):
        for action_type in _UNIQUE_ANDROID_ACTION_TYPES:
            with self.subTest(action_type=action_type):
                self.obox._queue_action(action_type, f"/odoo/{action_type}")

                with self.assertRaises(UserError):
                    self.obox._queue_action(action_type, f"/odoo/{action_type}")

    def test_an_android_unique_action_is_unique_per_box_only(self):
        other_obox = self.env["obox.obox"].create({
            "name": "Other Obox",
            "serial_number": "OTHER",
            "state": "02_paired",
            "token": "other_obox_token",
        })
        self.obox.action_request_screenshot()

        other_obox.action_request_screenshot()

        self.assertEqual(len(self._pending("screenshot")), 1)

    def test_a_sync_request_is_not_an_android_unique_action(self):
        first = self.obox._queue_action("request_sync", "/odoo/sync")
        second = self.obox._queue_action("request_sync", "/odoo/sync")

        self.assertNotEqual(first, second)

    def test_asking_a_printer_status_queues_the_command(self):
        self.obox_printer.action_printer_status()

        payload = self._pending("printer_status").payload
        self.assertEqual(payload["url"], "/usb/v1/printer/status")
        self.assertEqual(payload["payload"], {"identifier": "test_obox_printer"})

    def test_the_printer_status_is_told_to_the_user_who_asked(self):
        self.obox_printer.action_printer_status()

        with patch.object(self.registry["res.users"], "_bus_send", autospec=True) as sent:
            self.respond_to_pending_actions({"status": "ok", "printer_status": "cover_open"})

        user, notification_type, notification = sent.call_args.args
        self.assertEqual(user, self.env.user)
        self.assertEqual(notification_type, "simple_notification")
        self.assertEqual(notification, {"type": "warning", "message": "The printer cover is open"})

    def test_an_unreadable_printer_status_is_told_to_the_user(self):
        self.obox_printer.action_printer_status()

        with patch.object(self.registry["res.users"], "_bus_send", autospec=True) as sent:
            self.respond_to_pending_actions({"error": "printer status not available"})

        self.assertEqual(sent.call_args.args[2]["message"], "The printer status could not be read")

    def test_the_printer_status_is_only_offered_by_a_box_that_reads_it(self):
        self.assertFalse(self.obox_printer.supports_printer_status)

        self.obox.services = ["usb", "printer_status"]

        self.assertTrue(self.obox_printer.supports_printer_status)
