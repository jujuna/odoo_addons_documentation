from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def load_web_menus(self, debug):
        """Add `gecCategory` to app root menus and `gecNameEn` to menus whose English name differs (non-English users).

        English names come from a names-only search, so load_menus does not run twice."""
        menus = super().load_web_menus(debug)
        categories = self._gec_app_categories()
        names_en = {}
        if self.env.lang and self.env.lang != 'en_US':
            ids = [menu['id'] for menu in menus.values() if menu['id'] != 'root']
            names_en = {
                menu.id: menu.name
                for menu in self.with_context(lang='en_US').search_fetch([('id', 'in', ids)], ['name'])
            }
        for menu in menus.values():
            if menu['id'] == menu['appID']:
                module = (menu['xmlid'] or '').split('.')[0]
                menu['gecCategory'] = categories.get(module)
            name_en = names_en.get(menu['id'])
            if name_en and name_en != menu['name']:
                menu['gecNameEn'] = name_en
        return menus

    @api.model
    @api.ormcache('self.env.lang')
    def _gec_app_categories(self):
        """Return {module name: {id, name, sequence}} of each installed module's top-level category.

        sudo: module records are admin-only. The cached dict is shared: do not mutate it."""
        modules = self.env['ir.module.module'].sudo().search_fetch(
            [('state', '=', 'installed'), ('category_id', '!=', False)],
            ['name', 'category_id'],
        )
        result = {}
        for module in modules:
            root = module.category_id
            while root.parent_id:
                root = root.parent_id
            result[module.name] = {
                'id': root.id,
                'name': root.name,
                'sequence': root.sequence or None,
            }
        return result

    @api.model
    @api.ormcache('frozenset(self.env.user._get_group_ids())', 'res_model')
    def _gec_app_menu_for_model(self, res_model):
        """Return the id of the visible app root menu that best matches `res_model`, or None.

        A model hook that raises ValueError (deleted menu) gives None, so systray_get_activities keeps working."""
        try:
            return self._get_best_backend_root_menu_id_for_model(res_model)
        except ValueError:
            return None
