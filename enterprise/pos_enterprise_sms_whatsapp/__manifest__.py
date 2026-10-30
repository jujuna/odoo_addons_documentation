{
    'name': 'POS Enterprise SMS Whatsapp',
    'category': 'Sales/Point of Sale',
    'summary': 'This module enables communication via WhatsApp and SMS in the preparation display',
    'depends': ['pos_enterprise', 'whatsapp', 'pos_sms', 'pos_restaurant', 'pos_self_order'],
    'data': [
        'data/sms_template.xml',
        'data/whatsapp_template.xml',
        'views/pos_prep_display_view.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
}
