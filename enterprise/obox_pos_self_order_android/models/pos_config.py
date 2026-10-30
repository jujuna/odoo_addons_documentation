from odoo import _, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    self_ordering_obox_id = fields.Many2one('obox.obox', domain="[('supports_kiosk', '=', True)]")

    def action_open_wizard(self):
        result = super().action_open_wizard()

        if not self.self_ordering_obox_id:
            if (
                result.get("tag") == "pos_self_order_mobile.open_kiosk"
                and not self.receipt_printer_ids
                and self.group_pos_manager_id in self.env.user.all_group_ids
            ):
                result["tag"] = "obox_pos_self_order_android.open_kiosk"
                result["params"].update(
                    config_id=self.id,
                    config_name=self.name,
                    linked_printers=",".join(self.preparation_printer_ids.obox_device_id.mapped("identifier")),
                )
            return result

        self.self_ordering_obox_id._open_kiosk(self)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'message': _("Opening the kiosk on %s", self.self_ordering_obox_id.name),
            },
        }
