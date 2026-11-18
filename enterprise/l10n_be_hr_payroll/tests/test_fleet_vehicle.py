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

    def test_vehicle_fuel_type_from_model(self):
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'Brand'})
        model = self.env['fleet.vehicle.model'].create({
            'name': 'Electric Model',
            'brand_id': brand.id,
            'default_fuel_type': 'electric',
        })
        # without the onchange of the form (import, RPC, ...)
        vehicle = self.env['fleet.vehicle'].create({'model_id': model.id})
        self.assertEqual(vehicle.fuel_type, 'electric')
        vehicle = self.env['fleet.vehicle'].create({'model_id': model.id, 'fuel_type': 'gasoline'})
        self.assertEqual(vehicle.fuel_type, 'gasoline')
        self.assertEqual(self.env['fleet.vehicle'].create({}).fuel_type, 'diesel')

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

    def test_car_atn_2024_co2_references(self):
        """ The reference CO2 emissions of 2024: 78 g/km for petrol engines, 65 g/km for diesel engines """
        be_company = self.env['res.company'].create({
            'name': 'Belgian Test Company',
            'country_id': self.env.ref('base.be').id,
        })
        vehicle = self.env['fleet.vehicle'].with_company(be_company)
        # 40000 x (5.5% + 0.1% x (120 - 78)) x 6/7
        self.assertAlmostEqual(
            vehicle._get_car_atn_from_values(date(2024, 1, 1), 40000.0, 'gasoline', 120, 'g/km', date(2024, 6, 1)),
            3325.71, places=2)
        # 40000 x (5.5% + 0.1% x (120 - 65)) x 6/7
        self.assertAlmostEqual(
            vehicle._get_car_atn_from_values(date(2024, 1, 1), 40000.0, 'diesel', 120, 'g/km', date(2024, 6, 1)),
            3771.43, places=2)

    def test_car_atn_without_co2(self):
        """ Without CO2 data, a car is assimilated to 205 g/km (petrol) or 195 g/km (diesel); an electric car
        keeps 0 g/km """
        be_company = self.env['res.company'].create({
            'name': 'Belgian Test Company',
            'country_id': self.env.ref('base.be').id,
        })
        vehicle = self.env['fleet.vehicle'].with_company(be_company)

        def yearly_atn(fuel_type, co2):
            return vehicle._get_car_atn_from_values(date(2026, 1, 1), 40000.0, fuel_type, co2, 'g/km', date(2026, 3, 1))

        self.assertAlmostEqual(yearly_atn('gasoline', 0), yearly_atn('gasoline', 205), places=2)
        self.assertAlmostEqual(yearly_atn('diesel', 0), yearly_atn('diesel', 195), places=2)
        # 40000 x 18% (maximum) x 6/7
        self.assertAlmostEqual(yearly_atn('diesel', 0), 6171.43, places=2)
        # 40000 x 4% x 6/7
        self.assertAlmostEqual(yearly_atn('electric', 0), 1371.43, places=2)

    def test_car_atn_age_started_months(self):
        be_company = self.env['res.company'].create({
            'name': 'Belgian Test Company',
            'country_id': self.env.ref('base.be').id,
        })
        vehicle = self.env['fleet.vehicle'].with_company(be_company)

        def yearly_atn(acquisition_date, atn_date):
            return vehicle._get_car_atn_from_values(acquisition_date, 40000.0, 'electric', 0, 'g/km', atn_date)

        # a started month counts as a full month: registered on 21 June 2024, the car is counted from 1 June 2024,
        # 100% until 31 May 2025, then 94% for the whole of June 2025
        # electric: 40000 x 4% x 6/7 x age coefficient
        registration = date(2024, 6, 21)
        self.assertAlmostEqual(yearly_atn(registration, date(2025, 5, 31)), 1371.43, places=2)
        self.assertAlmostEqual(yearly_atn(registration, date(2025, 6, 1)), 1289.14, places=2)
        self.assertAlmostEqual(yearly_atn(registration, date(2025, 6, 20)), 1289.14, places=2)
        self.assertAlmostEqual(yearly_atn(registration, date(2026, 5, 31)), 1289.14, places=2)
        self.assertAlmostEqual(yearly_atn(registration, date(2026, 6, 1)), 1206.86, places=2)
        # from the 61st month on: 70%
        self.assertAlmostEqual(yearly_atn(registration, date(2029, 5, 31)), 1042.29, places=2)
        self.assertAlmostEqual(yearly_atn(registration, date(2029, 6, 1)), 960.0, places=2)

    def test_co2_fee_2027_indexation(self):
        # ONSS indexation: health index of September of the previous year (base 1996) / 114.08
        # 2026: 185.85, 2027: 193.27
        be_company = self.env['res.company'].create({
            'name': 'Belgian Test Company',
            'country_id': self.env.ref('base.be').id,
        })
        brand = self.env['fleet.vehicle.model.brand'].create({'name': 'BE Brand'})
        model = self.env['fleet.vehicle.model'].create({'name': 'BE Model', 'brand_id': brand.id})
        old_car, greening_car = self.env['fleet.vehicle'].with_company(be_company).create([{
            'model_id': model.id,
            'company_id': be_company.id,
            'contract_date_start': date(2020, 1, 1),
        }, {
            'model_id': model.id,
            'company_id': be_company.id,
            'contract_date_start': date(2023, 7, 15),
        }])

        def co2_fee(car, fee_date, fuel_type, co2):
            return car.with_context(co2_fee_date=fee_date)._get_co2_fee(co2, 'g/km', fuel_type)

        # 2024: the minimum of a car ordered from 1 July 2023 is still the ordinary one (the greening raises it from
        # 2025), as a payslip of 2024 computes it (the reference year of a double holiday pay)
        self.assertAlmostEqual(
            co2_fee(greening_car, date(2024, 3, 1), 'electric', 0), co2_fee(old_car, date(2024, 3, 1), 'electric', 0), places=2)
        # without CO2 data: 165 g/km for diesel, 182 g/km for petrol
        self.assertAlmostEqual(co2_fee(old_car, date(2026, 12, 1), 'diesel', 0), co2_fee(old_car, date(2026, 12, 1), 'diesel', 165), places=2)
        self.assertAlmostEqual(co2_fee(old_car, date(2026, 12, 1), 'gasoline', 0), co2_fee(old_car, date(2026, 12, 1), 'gasoline', 182), places=2)
        self.assertGreater(co2_fee(old_car, date(2026, 12, 1), 'gasoline', 0), 33.93)

        # 2026 unchanged
        # minimum: 20.83 x 185.85 / 114.08, greening minimum: 25.99 x 185.85 / 114.08
        self.assertAlmostEqual(co2_fee(old_car, date(2026, 12, 1), 'electric', 0), 33.93, places=2)
        self.assertAlmostEqual(co2_fee(greening_car, date(2026, 12, 1), 'electric', 0), 42.34, places=2)
        # diesel: ((130 x 9 - 600) / 12) x 185.85 / 114.08, x 4.00 for the greening car
        self.assertAlmostEqual(co2_fee(old_car, date(2026, 12, 1), 'diesel', 130), 77.38, places=2)
        self.assertAlmostEqual(co2_fee(greening_car, date(2026, 12, 1), 'diesel', 130), 309.53, places=2)

        # 2027
        # minimum: 20.83 x 193.27 / 114.08, greening minimum: 28.57 x 193.27 / 114.08
        self.assertAlmostEqual(co2_fee(old_car, date(2027, 1, 1), 'electric', 0), 35.29, places=2)
        self.assertAlmostEqual(co2_fee(greening_car, date(2027, 1, 1), 'electric', 0), 48.40, places=2)
        # diesel: ((130 x 9 - 600) / 12) x 193.27 / 114.08, x 5.50 for the greening car
        self.assertAlmostEqual(co2_fee(old_car, date(2027, 1, 1), 'diesel', 130), 80.47, places=2)
        self.assertAlmostEqual(co2_fee(greening_car, date(2027, 1, 1), 'diesel', 130), 442.60, places=2)
        # petrol: ((140 x 9 - 768) / 12) x 193.27 / 114.08
        self.assertAlmostEqual(co2_fee(old_car, date(2027, 1, 1), 'gasoline', 140), 69.46, places=2)
        # LPG: ((130 x 9 - 990) / 12) x 193.27 / 114.08 = 25.41, raised to the minimum
        self.assertAlmostEqual(co2_fee(old_car, date(2027, 1, 1), 'lpg', 130), 35.29, places=2)
