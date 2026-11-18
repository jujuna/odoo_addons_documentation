# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class HrEmployeeDeparture(models.Model):
    _inherit = "hr.employee.departure"

    def _l10n_ae_use_uae_reasons(self):
        # The UAE reasons are loaded by the module update: keep the generic ones until then
        return self.env.company.country_id.code == 'AE' and bool(
            self.env['hr.departure.reason'].search_count([('country_id.code', '=', 'AE')], limit=1))

    def _get_departure_reason_domain(self):
        """
        For Emirati companies, the departure reasons are very specific and some of the generic reasons do not make sense.
        If the currently selected company is in Emirati, only show Emirati specific reasons, else return the normal domain.
        """
        if self._l10n_ae_use_uae_reasons():
            return [('country_id.code', '=', 'AE')]
        return super()._get_departure_reason_domain()

    def _get_default_departure_reason(self):
        # The UAE reason drives the visa cancellation: it is always chosen by the user
        if self._l10n_ae_use_uae_reasons():
            return self.env['hr.departure.reason']
        return super()._get_default_departure_reason()
