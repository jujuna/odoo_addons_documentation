import json

from odoo import api, fields, models

_UNIQUE_ANDROID_ACTION_TYPES = ["screenshot", "logs", "open_kiosk", "kiosk_screen_lock", "kiosk_reload", "kiosk_update"]


class OboxQueue(models.TransientModel):
    _inherit = "obox.queue"

    action_type = fields.Selection(
        selection_add=[
            ("request_sync", "Request Sync"),
            ("screenshot", "Screenshot"),
            ("logs", "Fetch Logs"),
            ("open_kiosk", "Open Kiosk"),
            ("kiosk_screen_lock", "Lock / Unlock Screen"),
            ("kiosk_reload", "Reload Kiosk"),
            ("kiosk_update", "Update App"),
            ("printer_status", "Printer Status"),
        ],
        ondelete={
            "request_sync": "cascade",
            "screenshot": "cascade",
            "logs": "cascade",
            "open_kiosk": "cascade",
            "kiosk_screen_lock": "cascade",
            "kiosk_reload": "cascade",
            "kiosk_update": "cascade",
            "printer_status": "cascade",
        },
    )

    @api.model
    def _get_unique_action_types(self):
        return [*super()._get_unique_action_types(), *_UNIQUE_ANDROID_ACTION_TYPES]

    def handle_obox_response(self, result):
        res = super().handle_obox_response(result)
        if self.action_type == "printer_status" and self.status == "done":
            status = json.loads(self.result).get("printer_status")
            self.create_uid._bus_send("simple_notification", {
                "type": "success" if status == "ready" else "warning",
                "message": self._printer_status_message(status),
            })
        return res

    def _printer_status_message(self, status):
        return {
            "ready": self.env._("The printer is ready"),
            "paper_near_end": self.env._("The printer is almost out of paper"),
            "paper_end": self.env._("The printer is out of paper"),
            "cover_open": self.env._("The printer cover is open"),
            "error": self.env._("The printer reports an error"),
            "not_responding": self.env._("The printer does not answer"),
            "offline": self.env._("The printer is offline"),
            "unsupported": self.env._("This printer does not report its status"),
        }.get(status, self.env._("The printer status could not be read"))
