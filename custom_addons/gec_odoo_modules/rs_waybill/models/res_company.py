from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    # A waybill belongs to a company, so each company decides on its own. Auto-Sync toggles stay global (they drive
    # ir.cron.active); the sync cursor stays an ir.config_parameter.
    rs_enable_stock = fields.Boolean(string='RS Enable Stock Integration',
                                     help='Off: this company\'s waybills stay waybills only, no sales/purchase orders, '
                                          'deliveries or receipts.')

    rs_stock_integration_date = fields.Date(string='RS Stock Integration Start Date',
                                            help='Waybills activated (or created) on or after this Georgian date get their '
                                                 'Odoo documents built automatically. Earlier ones stay data-only.')

    rs_mapping_cutoff_date = fields.Date(string='RS Apply Product Mapping From',
                                         help='Waybills created on or after this Georgian date are subject to the '
                                              'product-mapping rules.')

    rs_notification_user_ids = fields.Many2many('res.users', 'rs_waybill_company_notify_users_rel', 'company_id', 'user_id',
                                                string='RS Waybill Notification Recipients')
