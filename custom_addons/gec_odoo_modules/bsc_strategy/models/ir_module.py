from odoo import api, models


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    @api.model
    def _bsc_ensure_listed_in_apps(self):
        """Give bsc_strategy the 'official' module_type so the Apps menu lists it.
        Modules found by ``-i``/``-u`` get no module_type and the Apps menu hides them.
Called from data/ir_module.xml on install and update."""
        if "module_type" not in self._fields:
            return True
        self.sudo().search([("name", "=", "bsc_strategy"), ("module_type", "=", False)]).write(
            {"module_type": "official"})
        return True
