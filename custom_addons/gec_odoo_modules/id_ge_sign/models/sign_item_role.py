from odoo import fields, models


class SignItemRole(models.Model):
    _inherit = 'sign.item.role'

    auth_method = fields.Selection(selection_add=[('geoeid', 'Georgian ID Card')], ondelete={'geoeid': 'set default'})

    def _compute_requires_external_signature(self):
        super()._compute_requires_external_signature()
        self.filtered(lambda role: role.auth_method == 'geoeid').requires_external_signature = True

    def _get_external_signature_provider_name(self):
        """Core's invite mail calls the signature qualified whenever a name is returned (mail_templates.xml:22-27)."""
        if self.auth_method == 'geoeid':
            return self.env._("Georgian ID Card")
        return super()._get_external_signature_provider_name()

    def _get_iap_service_name(self):
        if self.auth_method == 'geoeid':
            return False
        return super()._get_iap_service_name()
