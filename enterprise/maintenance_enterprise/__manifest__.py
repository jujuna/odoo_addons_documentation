# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Enterprise Maintenance',
    'category': 'Supply Chain/Maintenance',
    'summary': "Advanced features for Maintenance",
    'description': "Contains the enterprise views for Stock management",
    'depends': ['maintenance', 'web_gantt'],
    'data': [
        'views/maintenance_views.xml',
    ],
    'assets': {
        'web.assets_backend_lazy': [
            'maintenance_enterprise/static/src/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'OEEL-1',
    'auto_install': True,
}
