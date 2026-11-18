from odoo import models

from odoo.tools.barcode import check_barcode_encoding


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _l10n_uy_edi_get_cod_items(self):
        """ B2 TpoCod, B3 Cod ("TABLA de Códigos del Ítem", up to 5 occurrences per item).

        Return the product codes to report so the receiver system can identify the item:
        the internal reference (INT1 code type) and the barcode (GTIN13 code type).
        The barcode is only reported when it is a valid EAN-13, since DGI validates
        the check digit of GTIN codes. """
        cod_items = []
        if not self:
            return cod_items
        self.ensure_one()
        if self.default_code:
            cod_items.append({"TpoCod": "INT1", "Cod": self.default_code[:35]})
        if self.barcode and check_barcode_encoding(self.barcode, "ean13"):
            cod_items.append({"TpoCod": "GTIN13", "Cod": self.barcode})
        return cod_items
