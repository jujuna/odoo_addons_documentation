# Part of the GEC Georgian translation modules.
import sys

from odoo import api, models

from ..hooks import force_apply_translations
from ..i18n_patch import AREA_MODULES, install_patch


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    @api.model
    def _load_module_terms(self, modules, langs, overwrite=False):
        """Also force-apply the files of every area module being installed or upgraded (see hooks.py)."""
        super()._load_module_terms(modules, langs, overwrite=overwrite)
        areas = [name for name in modules if name in AREA_MODULES]
        if areas:
            force_apply_translations(self.env, areas, langs)

    def _register_hook(self):
        """Patch mail's template reset, which imports get_po_paths by name and loads after us."""
        super()._register_hook()
        reset_mixin = sys.modules.get('odoo.addons.mail.models.template_reset_mixin')
        if reset_mixin:
            install_patch(reset_mixin)
