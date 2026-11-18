from odoo import models


class RsSoapService(models.AbstractModel):
    _inherit = 'rs.soap.service'

    def get_buyer_invoices(self, *args, **kwargs):
        """The petroleum inbox runs the ordinary search with this context key; the login and taxpayer id are shared."""
        if not self.env.context.get('rs_spec_inbox'):
            return super().get_buyer_invoices(*args, **kwargs)
        return self.env['rs.spec.soap.service'].get_buyer_invoices(*args, **kwargs)
