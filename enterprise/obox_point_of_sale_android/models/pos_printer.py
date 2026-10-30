from odoo import api, models


class PosPrinter(models.Model):
    _inherit = "pos.printer"

    @api.onchange("obox_device_id")
    def _onchange_obox_device_id(self):
        super()._onchange_obox_device_id()
        for record in self:
            if record.obox_device_id:
                record.printer_ip = record._obox_printer_ip()

    def _obox_printer_ip(self):
        self.ensure_one()
        return f"{self.obox_device_id.obox_id.local_address}/usb/v1/printer/{self.obox_device_id.identifier}"
