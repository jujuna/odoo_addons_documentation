{
    'name': "Hotel Revenue Management - Sales & Pricelist",
    'version': '1.0',
    'category': 'Sales',
    'summary': "Read bookings and nightly prices from rental orders and the pricelist",
    'description': """
Connects Hotel Revenue Management to rental sales orders and a pricelist. Rental order lines
become the reservations of the hotel, and the pricelist gives the current price of each night.
Approved prices are written back to the pricelist as one fixed price per night and room product.
Full documentation: README.md in the module directory.
""",
    'author': "GEC",
    'license': 'LGPL-3',
    'depends': ['hotel_rms', 'sale_renting'],
    'data': [
        'views/hotel_rms_sale_views.xml',
    ],
    'installable': True,
    'auto_install': True,
}
