from datetime import date

from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install', 'post_install_l10n')
class TestFleetVehicle(TransactionCase):

    def test_fleet_vehicle_model_atn_non_belgian_company_no_error(self):
        fr_company = self.env['res.company'].create({
            'name': 'French Test Company',
            'country_id': self.env.ref('base.fr').id,
        })

        brand = self.env['fleet.vehicle.model.brand'].sudo().create({'name': 'FR Brand'})
        fr_model = self.env['fleet.vehicle.model'].sudo().with_company(fr_company).create({
            'name': 'FR Model',
            'brand_id': brand.id,
            'default_car_value': 30000.0,
            'default_fuel_type': 'diesel',
            'default_co2': 90.0,
        })

        # Trigger computation and assert no exception was raised and default_atn evaluates to 0.0
        self.assertEqual(fr_model.current_country_code, 'FR')
        self.assertEqual(fr_model.default_atn, 0.0)

    def test_plug_in_hybrid_car_atn_fuel_reference(self):
        be_company = self.env['res.company'].create({
            'name': 'Belgian Test Company',
            'country_id': self.env.ref('base.be').id,
        })
        vehicle = self.env['fleet.vehicle'].with_company(be_company)

        def yearly_atn(fuel_type, co2):
            return vehicle._get_car_atn_from_values(date(2026, 1, 1), 40000.0, fuel_type, co2, 'g/km', date(2026, 3, 1))

        # 2026 references: 58 g/km for diesel engines, 70 g/km for petrol engines
        # diesel plug-in hybrid: 40000 x (5.5% + 0.1% x (106 - 58)) x 6/7
        self.assertAlmostEqual(yearly_atn('plug_in_hybrid_diesel', 106), 3531.43, places=2)
        self.assertAlmostEqual(yearly_atn('plug_in_hybrid_diesel', 106), yearly_atn('diesel', 106), places=2)
        # under 50 g/km, the percentage still follows the diesel reference: 5.5% + 0.1% x (45 - 58) = 4.2%
        self.assertAlmostEqual(yearly_atn('plug_in_hybrid_diesel', 45), 1440.0, places=2)
        # petrol plug-in hybrid: 5.5% + 0.1% x (45 - 70) = 3.0%, raised to the 4% floor
        self.assertAlmostEqual(yearly_atn('plug_in_hybrid_gasoline', 45), 1371.43, places=2)
        self.assertAlmostEqual(yearly_atn('plug_in_hybrid_gasoline', 106), yearly_atn('gasoline', 106), places=2)
