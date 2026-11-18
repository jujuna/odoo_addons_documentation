{
    'name': "Hotel Revenue Management",
    'version': '1.0',
    'category': 'Sales',
    'summary': "Explainable occupancy forecast and nightly price recommendations for hotels",
    'description': """
Forecasts the occupancy of every night, recommends a price per night and room type
within the safety rules of the hotel, and explains each recommendation in plain words.
A revenue manager accepts, changes, rejects, undoes or locks each price and exports
the approved prices to a CSV file.
Full documentation: README.md in the module directory.
""",
    'author': "GEC",
    'license': 'LGPL-3',
    'depends': ['mail'],
    'data': [
        'security/hotel_rms_security.xml',
        'data/hotel_rms_cron.xml',
        'views/hotel_rms_calendar_action.xml',
        'views/hotel_rms_event_views.xml',
        'views/hotel_rms_reservation_views.xml',
        'views/hotel_rms_forecast_views.xml',
        'views/hotel_rms_price_views.xml',
        'views/hotel_rms_price_audit_views.xml',
        'views/hotel_rms_run_views.xml',
        'views/hotel_rms_import_views.xml',
        'views/hotel_rms_property_views.xml',
        'views/hotel_rms_menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': ['hotel_rms/static/src/**/*'],
    },
    'installable': True,
    'application': True,
}
