from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    rs_is_driver = fields.Boolean(string='Is RS Driver', default=False, index=True,
                                  help='Marks this partner as a driver registered in the RS.GE system.',)
    rs_is_foreigner = fields.Boolean(string='Driver is Foreigner', default=False,
                                     help='True if the driver is not a Georgian citizen — affects CHEK_DRIVER_TIN in the RS waybill XML.',)
    rs_name_locked = fields.Boolean(string='Lock RS-synced name', default=False,
                                    help='If True, name will never be overwritten by RS sync. '
                                         'Set when operator manually edits the partner name and wants to keep it.',)


    @api.model
    def _rs_driver_from_tin(self, tin, name=None, company=None):
        """ The driver with this TIN (marked RS driver), created with RS.GE's name for it if new. Empty for an empty
            TIN or a contact only another company owns. """
        tin = (tin or '').strip()
        if not tin:
            return self.env['res.partner']
        company = company or self.env.company
        found = self.sudo().search([('vat', '=', tin)])
        driver = self.browse(found.filtered(lambda p: not p.company_id or p.company_id == company)[:1].id)
        if not driver and found:
            return self.env['res.partner']
        if driver:
            if not driver.rs_is_driver:
                driver.rs_is_driver = True
            return driver
        try:
            rs_name = self.env['rs.waybill.soap.service'].with_company(company).get_transporter_info(tin)
        except Exception as e:
            _logger.warning("RS get_name_from_tin failed for %s: %s", tin, e)
            rs_name = ''
        return self.create({'name': rs_name or name or tin, 'vat': tin, 'rs_is_driver': True, 'is_company': False})


    @api.model
    def name_create(self, name):
        """ A TIN typed in the waybill's driver field: that driver, fetched from RS.GE when new. """
        if self.env.context.get('rs_driver_name_create') and (name or '').strip():
            driver = self._rs_driver_from_tin(name)
            return driver.id, driver.display_name
        return super().name_create(name)


    @api.depends('vat', 'name')
    @api.depends_context('show_partner_tin')
    def _compute_display_name(self):
        """ The waybill's Driver TIN dropdown (context show_partner_tin) shows 'TIN — Name'. """
        if self.env.context.get('show_partner_tin'):
            for partner in self:
                partner.display_name = ' — '.join(p for p in (partner.vat, partner.name) if p)
            return
        super()._compute_display_name()
