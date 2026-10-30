import ipaddress

from odoo import api, fields, models

_ADDRESS_FIELDS = frozenset({"local_ip", "local_port"})


class OboxObox(models.Model):
    _inherit = 'obox.obox'

    @api.model
    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'local_port', 'local_address']

    def write(self, vals):
        moved = self.filtered(
            lambda box: any(field in vals and box[field] != vals[field] for field in _ADDRESS_FIELDS),
        )
        res = super().write(vals)
        moved._update_pos_printer_addresses()
        return res

    def _has_valid_local_ip(self):
        self.ensure_one()
        try:
            ip = ipaddress.IPv4Address((self.local_ip or "").strip())
        except ipaddress.AddressValueError:
            return False
        return not (ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast)

    def _update_pos_printer_addresses(self):
        boxes = self.filtered(lambda box: box.platform == "android" and box._has_valid_local_ip())
        if not boxes:
            return
        printers = self.env["pos.printer"].search([
            ("printer_type", "=", "obox"),
            ("obox_device_id.obox_id", "in", boxes.ids),
        ])
        for printer in printers:
            printer.printer_ip = printer._obox_printer_ip()

    def _get_obox_features(self):
        features = super()._get_obox_features()
        if self._search_obox_pos_configs(self._get_obox_feature_pos_domain(), limit=1):
            features.append("point_of_sale")
        return features

    def _get_obox_feature_pos_domain(self):
        return []

    def _search_obox_pos_configs(self, domain, limit=None):
        return self.env["pos.config"].with_context(active_test=True).search(domain, limit=limit)

    def _get_obox_feature_details(self, name):
        feature_detail = super()._get_obox_feature_details(name)

        if name != "point_of_sale":
            return feature_detail

        pos_configs = self._search_obox_pos_configs(self._get_obox_feature_pos_domain())
        feature_detail["point_of_sale"] = [
            {
                "id": config.id,
                "name": config.name,
                "url": f"{config.get_base_url()}/pos/ui/{config.id}",
                "timezone": config.company_id.tz,
                "app": "point_of_sale",
                "linked_printers": (config.receipt_printer_ids | config.preparation_printer_ids).obox_device_id.mapped("identifier"),
            }
            for config in pos_configs
        ]

        return feature_detail

    def _add_obox_receipt_printer(self, config_id, identifier, paper_size=None):
        self.ensure_one()
        device = self.device_ids.filtered(lambda d: d.type == "printer" and d.identifier == identifier)
        config = self._search_obox_pos_configs([("id", "=", config_id)])
        if not device or not config:
            return False
        printer = self.env["pos.printer"].search([
            ("obox_device_id", "=", device.id),
            ("use_type", "=", "receipt"),
        ], limit=1)
        if not printer:
            vals = {
                "name": device.name,
                "printer_type": "obox",
                "use_type": "receipt",
                "use_lna": True,
                "obox_device_id": device.id,
            }
            if paper_size in self.env["pos.printer"]._fields["paper_size"].get_values(self.env):
                vals["paper_size"] = paper_size
            printer = self.env["pos.printer"].create(vals)
            printer.printer_ip = printer._obox_printer_ip()
        config.write({"other_devices": True, "receipt_printer_ids": [fields.Command.link(printer.id)]})
        return True
