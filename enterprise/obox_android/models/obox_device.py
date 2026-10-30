from odoo import fields, models


class OboxDevice(models.Model):
    _inherit = "obox.device"

    # Includes the port the box listens on, used as the address to reach the device.
    local_ip = fields.Char(string="Local IP", related="obox_id.local_address")
    local_port = fields.Integer(related="obox_id.local_port")
    local_address = fields.Char(related="obox_id.local_address")
    supports_printer_status = fields.Boolean(related="obox_id.supports_printer_status")

    def action_printer_status(self):
        self.ensure_one()
        self.obox_id._queue_action("printer_status", "/usb/v1/printer/status", {"identifier": self.identifier})
        return self.obox_id._command_sent_notification()

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get("obox_sync") and "name" in vals:
            for device in self:
                if device.obox_id.supports_sync:
                    device.obox_id._request_sync()
        return res
