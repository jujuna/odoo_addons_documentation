from odoo import models


class IrModuleCategory(models.Model):
    """Changing a category's name, parent or sequence clears the cache of ir.ui.menu._gec_app_categories."""
    _inherit = 'ir.module.category'
    _clear_cache_name = 'default'
    _clear_cache_on_fields = ('name', 'parent_id', 'sequence')
