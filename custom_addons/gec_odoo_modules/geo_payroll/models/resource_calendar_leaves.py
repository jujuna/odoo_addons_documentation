import logging

from odoo import api, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

FOREIGN_PUBLIC_HOLIDAYS_KEY = 'geo_payroll.foreign_public_holidays_removed'


class ResourceCalendarLeaves(models.Model):
    _inherit = 'resource.calendar.leaves'

    @api.model
    def _gec_remove_foreign_public_holidays(self, companies=None):
        """A company country change leaves its public holidays typed for the old country, unreadable to its users."""
        params = self.env['ir.config_parameter'].sudo()
        if companies is None and params.get_bool(FOREIGN_PUBLIC_HOLIDAYS_KEY):
            return
        domain = Domain('resource_id', '=', False) & Domain('work_entry_type_id.country_id', '!=', False)
        if companies is not None:
            domain &= Domain('company_id', 'in', companies.ids)
        # sudo: the old country's time type is hidden from the company's users by the hr.work.entry.type country restriction
        leaves = self.sudo().search(domain)
        stale = leaves.filtered(lambda leave: (country := leave.calendar_id.company_id.country_id or leave.company_id.country_id)
            and leave.work_entry_type_id.country_id != country)
        if stale:
            _logger.info("Removing %s public holidays typed for another country: %s", len(stale), stale.ids)
            stale.unlink()
        if companies is None:
            params.set_bool(FOREIGN_PUBLIC_HOLIDAYS_KEY, True)
