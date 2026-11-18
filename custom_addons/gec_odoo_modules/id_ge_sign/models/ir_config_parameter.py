from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.tools import file_open

from odoo.addons.id_ge_sign.tools.cms import _load_anchors


class IrConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    @api.model
    def _geoeid_fill_trust_anchor(self):
        """An admin's value is kept: the state's certificates fill only an empty key."""
        if not self.get_str('id_ge_sign.trust_anchor'):
            with file_open('id_ge_sign/data/geo_signing_ca.pem') as certificates:
                self.set_str('id_ge_sign.trust_anchor', certificates.read())

    @api.constrains('key', 'value')
    def _check_geoeid_trust_anchor(self):
        for parameter in self.filtered(lambda record: record.key == 'id_ge_sign.trust_anchor' and record.value):
            try:
                if not _load_anchors([parameter.value]):
                    raise ValueError("No certificates found")
            except ValueError as exc:
                raise ValidationError(self.env._("Set valid PEM certificates for Georgian ID signing.")) from exc
