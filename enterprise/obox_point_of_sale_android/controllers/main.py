from odoo import http

from odoo.addons.obox.controllers.main import _check_obox_access


class OboxPosAndroidController(http.Controller):
    @http.route("/obox/pos/add_receipt_printer", auth="public", type="jsonrpc")
    def obox_add_receipt_printer(self, serial_number, token, config_id, identifier, name=None, paper_size=None):
        box = _check_obox_access(serial_number, token)
        if name:
            box._sync_devices([{"identifier": identifier, "name": name, "type": "printer"}])
        return box._add_obox_receipt_printer(config_id, identifier, paper_size)
