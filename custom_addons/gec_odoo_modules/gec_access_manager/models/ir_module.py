from odoo import _, models


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def _gec_check_apps(self, method):
        rules = self.env['gec.access.profile']._current_rules()
        if rules.enabled and rules.has_flag('block_apps'):
            raise self.env['gec.access.profile']._gec_refusal(
                _("Your access profile does not allow installing, upgrading or uninstalling apps."),
                model=self._name, method=method, record_ids=self.ids)

    def button_install(self):
        self._gec_check_apps('button_install')
        return super().button_install()

    def button_immediate_install(self):
        self._gec_check_apps('button_immediate_install')
        return super().button_immediate_install()

    def button_upgrade(self):
        self._gec_check_apps('button_upgrade')
        return super().button_upgrade()

    def button_immediate_upgrade(self):
        self._gec_check_apps('button_immediate_upgrade')
        return super().button_immediate_upgrade()

    def button_uninstall(self):
        self._gec_check_apps('button_uninstall')
        return super().button_uninstall()

    def button_immediate_uninstall(self):
        self._gec_check_apps('button_immediate_uninstall')
        return super().button_immediate_uninstall()
