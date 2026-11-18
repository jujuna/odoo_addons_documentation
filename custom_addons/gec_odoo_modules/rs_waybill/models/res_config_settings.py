from odoo import models, api, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rs_notification_user_ids = fields.Many2many(related='company_id.rs_notification_user_ids', readonly=False,
                                             string='Waybill Notification Recipients')
    rs_stock_integration_date = fields.Date(related='company_id.rs_stock_integration_date', readonly=False,
                                            string='Stock Integration Start Date')
    rs_enable_stock = fields.Boolean(related='company_id.rs_enable_stock', readonly=False,
                                     string='Enable Stock Integration')
    rs_mapping_cutoff_date = fields.Date(related='company_id.rs_mapping_cutoff_date', readonly=False,
                                         string='Apply Product Mapping From')

    # Database-wide. Products / Drivers only show their import buttons on this page.
    rs_enable_products = fields.Boolean(string='Enable RS.GE Products', config_parameter='rs_waybill.enable_products')
    rs_enable_drivers = fields.Boolean(string='Enable RS.GE Drivers', config_parameter='rs_waybill.enable_drivers')
    # The jobs' own active flag (ir.cron has no company): no separate parameter that could disagree with it.
    rs_auto_sync_updated = fields.Boolean(string='Auto-Sync Updated Waybills')
    rs_auto_sync_transporter = fields.Boolean(string='Auto-Sync Transporter Waybills')


    def action_sync_templates(self):
        return self.env['rs.waybill'].action_sync_templates()

    def action_update_rs_products(self):
        return self.env['product.product'].action_update_rs_products()

    def action_update_car_numbers(self):
        return self.env['fleet.vehicle'].action_update_rs_vehicle()

    def action_sync_seller_waybills(self):
        return self.env['rs.waybill'].action_sync_seller_waybills()

    def action_sync_buyer_waybills(self):
        return self.env['rs.waybill'].action_sync_buyer_waybills()

    def action_sync_transporter_waybills(self):
        return self.env['rs.waybill'].action_sync_transporter_waybills()

    def action_sync_all_waybills(self):
        return self.env['rs.waybill'].action_sync_all()

    def _rs_sync_crons(self):
        """ {settings field: its ir.cron} for the Auto-Sync switches; a deleted job is left out. """
        crons = {'rs_auto_sync_updated': 'rs_waybill.ir_cron_sync_updated_waybills',
                 'rs_auto_sync_transporter': 'rs_waybill.cron_sync_transporter_waybills'}
        crons = {field: self.env.ref(xmlid, raise_if_not_found=False) for field, xmlid in crons.items()}
        return {field: cron for field, cron in crons.items() if cron}

    @api.model
    def get_values(self):
        """ The Auto-Sync boxes show whether the jobs run, so saving Settings never switches one off unasked. """
        res = super().get_values()
        res.update({field: cron.sudo().active
                    for field, cron in self._rs_sync_crons().items()})
        return res

    def set_values(self):
        """ Per-company settings are related fields; only the DB-wide cron switches are handled here. """
        res = super().set_values()
        for field, cron in self._rs_sync_crons().items():
            if cron.sudo().active != self[field]:
                cron.sudo().active = self[field]
        return res


