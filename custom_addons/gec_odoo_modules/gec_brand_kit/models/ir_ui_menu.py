from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def load_web_menus(self, debug):
        """Pass the brand kit home background URL on the root menu (`gecBrandBackgroundUrl`).

        Done here and not in load_menus: that result is ormcached and its root is rebuilt from a fixed
        key list in web's load_web_menus. The `unique` value changes with each new picture."""
        menus = super().load_web_menus(debug)
        kit = self.env['gec.brand.kit']._get_applied()
        if kit.home_background and 'root' in menus:
            unique = int(kit.write_date.timestamp())
            menus['root']['gecBrandBackgroundUrl'] = f'/web/image/gec.brand.kit/{kit.id}/home_background?unique={unique}'
        return menus
