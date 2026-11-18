from odoo import _, models

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE


class PosSession(models.Model):
    _inherit = 'pos.session'

    def close_session_from_ui(self, payment_method_closing=None):
        result = super().close_session_from_ui(payment_method_closing or {})
        if result.get('type') == 'draft_orders' and (glovo_message := self._get_glovo_draft_orders_message()):
            result['message'] = f"{result['message']} {glovo_message}"
        return result

    def _get_glovo_draft_orders_message(self):
        """Glovo drafts wait for Glovo's picked-up or cancelled notification; only a POS manager can resolve them."""
        orders = self.get_session_orders().filtered(lambda o: o.state == 'draft' and o.platform_order_provider_code == PROVIDER_CODE)
        if not orders:
            return ""
        return _("Ask a POS manager to resolve Glovo order %s.", ", ".join(orders.mapped('platform_order_ref')))
