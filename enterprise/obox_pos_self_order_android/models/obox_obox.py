from odoo import api, models


class OboxObox(models.Model):
    _inherit = 'obox.obox'

    @api.model
    def _load_pos_self_data_fields(self, config):
        return [*super()._load_pos_self_data_fields(config), 'local_address']

    def _get_obox_feature_pos_domain(self):
        return [*super()._get_obox_feature_pos_domain(), ("self_ordering_mode", "!=", "kiosk")]

    def _get_obox_features(self):
        features = super()._get_obox_features()
        if self._search_obox_pos_configs([("self_ordering_mode", "=", "kiosk")], limit=1):
            features.append("kiosk")
        return features

    def _get_obox_feature_details(self, name):
        feature_detail = super()._get_obox_feature_details(name)

        if name != "kiosk":
            return feature_detail

        kiosk_configs = self._search_obox_pos_configs([("self_ordering_mode", "=", "kiosk")])
        feature_detail["kiosk"] = [
            {
                "id": config.id,
                "name": config.name,
                "url": config.get_kiosk_url(),
                "timezone": config.company_id.tz,
                "app": "point_of_sale",
                "linked_printers": None if config.receipt_printer_ids else config.preparation_printer_ids.obox_device_id.mapped("identifier"),
            }
            for config in kiosk_configs
        ]

        return feature_detail
