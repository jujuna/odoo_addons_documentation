{
    'name': 'Waybill - Revenue Service(Georgia)',
    'version': '20.0.1.0.4',
    'category': 'Supply Chain/Inventory',
    'description': """
Integrates Odoo with the Georgian Revenue Service (RS.GE) waybill service.

Sales orders create waybills as soon as their delivery reserves stock. Drivers, vehicles,
transporters and product mappings are managed in Odoo, and the full RS waybill lifecycle
(save, send, edit, close, cancel, refuse) runs from buttons that call the RS.GE SOAP API.
Buyer-side and transporter waybills are supported; background jobs sync templates and
waybills from RS.GE.

Developer documentation: README.md in the module folder.
""",
    'author': 'GEC - Business Growth Services',
    'web_icon': 'rs_waybill,static/description/icon.png',
    'depends': [
        'base','mail','product','stock','account','fleet','sale','sale_stock','purchase','purchase_stock','base_setup','account_edi_ubl_cii',
    ],
    'data': [
        'security/rs_waybill_groups.xml',
        'views/rs_waybill_list_views.xml',
        'views/rs_waybill_views.xml',
        'views/rs_waybill_driver_views.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
        'views/mapping_wizard_views.xml',
        'views/template_wizards_views.xml',
        'views/rs_waybill_menu.xml',
        'views/rs_waybill_analysis_views.xml',
        'views/uom_uom_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking.xml',
        'views/rs_waybill_adjustment_views.xml',
        'views/return_decision_wizard_views.xml',
        'views/live_rs_view_views.xml',
        'views/rs_excise_code_views.xml',
        'data/uom_data.xml',
        'data/ir_cron.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': [
            'rs_waybill/static/src/scss/rs_waybill_tokens.scss',
            'rs_waybill/static/src/scss/rs_waybill_base.scss',
            'rs_waybill/static/src/scss/rs_waybill_form.scss',
            'rs_waybill/static/src/scss/rs_waybill_list.scss',
            'rs_waybill/static/src/scss/rs_waybill_dialogs.scss',
            'rs_waybill/static/src/dashboard/waybill_list_kpis.js',
            'rs_waybill/static/src/dashboard/waybill_list_kpis.xml',
            'rs_waybill/static/src/dashboard/waybill_state_icon.js',
            'rs_waybill/static/src/dashboard/waybill_state_icon.xml',
            'rs_waybill/static/src/dashboard/waybill_live_form.js',
        ],
    },
    'external_dependencies': {'python': ['zeep', 'lxml']},
    # AGPL-3 to match rs_base_methods, which builds on this module.
    'license': 'AGPL-3',
    'post_init_hook': '_rs_create_pickup_types',
    'application': True,
}
