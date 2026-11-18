from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE


class PlatformOrderProvider(models.Model):
    _inherit = 'platform.order.provider'

    code = fields.Selection(selection_add=[('glovo', "Glovo")], ondelete={'glovo': 'set default'})
    glovo_token = fields.Char(string="Glovo Token",
        help="Static token from the Glovo account manager. Sent on every API call and checked on every Glovo notification.",
        groups='point_of_sale.group_pos_manager', copy=False)

    @api.constrains('glovo_token')
    def _check_glovo_token_ascii(self):
        """HTTP headers arrive as latin-1, so a non-ASCII token could never match a notification."""
        for provider in self:
            if provider.glovo_token and not provider.glovo_token.isascii():
                raise ValidationError(self.env._("The Glovo token must contain only ASCII characters."))

    @api.model
    def _get_provider_payment_method(self, code, company_ids):
        """Core creates the journal with the upper-case code but searches it by the provider code: find Glovo's again."""
        return super()._get_provider_payment_method(code.upper() if code == PROVIDER_CODE else code, company_ids)

    @api.model
    def _get_provider_pricelist(self, code, company_ids):
        """Core creates the pricelist without a company but searches it by company: find Glovo's shared one too."""
        pricelist = super()._get_provider_pricelist(code, company_ids)
        if code != PROVIDER_CODE or pricelist:
            return pricelist
        return super()._get_provider_pricelist(code, [False])[:1]

    @api.model
    def _remove_provider(self, code):
        """Core's removal without deleting Glovo's journal, payment method and pricelist: they can carry payments.

        A reinstall finds and reuses them through the lookups above.
        """
        if code != PROVIDER_CODE:
            return super()._remove_provider(code)
        providers = self.search(self._get_provider_domain(code), order='id')
        providers.write(self._get_removal_values())
        (providers - providers[:1]).unlink()
        return None
