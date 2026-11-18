from odoo import models


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'
    _description = "Sales Advance Payment Invoice"

    def _prepare_down_payment_invoice_line_values(self, order, so_line, account):
        """
        Extends 'sale'
        The description of the down payment product line must be "Anticipo
        del bien o servicio", according to the Anexo 20, Appendix 6,
        Section A, page 72 and Appendix 6, Section B, page 75.
        """
        res = super()._prepare_down_payment_invoice_line_values(order, so_line, account)
        if order.country_code == 'MX':
            res['name'] = 'Anticipo del bien o servicio'

        return res
