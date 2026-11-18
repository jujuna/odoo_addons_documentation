"""Driver and car are looked up in the waybill's company. A plate is unique across companies, so another company's
car is not linked (RS.GE gets the plate text either way)."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestDriverVehicleCompany(RsWaybillCommon):

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({'name': 'Company B', 'vat': '405000005'})
        self.env.user.company_ids |= self.company_b
        # Company A active, both ticked: the user works on B's waybill from A.
        self.env = self.env(context=dict(self.env.context,
                                         allowed_company_ids=[self.company_a.id, self.company_b.id]))
        patcher = patch.object(type(self.env['rs.waybill.soap.service']), 'get_transporter_info',
                               return_value='')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _b_waybill(self, plate, tin='01001000077'):
        waybill = self.make_waybill(company_id=self.company_b.id, car_number=plate,
                                    driver_tin=tin, driver_name='Driver B')
        waybill._rs_resolve_driver_and_vehicle()
        return waybill

    def test_new_plate_is_created_in_the_waybill_company(self):
        waybill = self._b_waybill('BB-777-BB')
        self.assertEqual(waybill.vehicle_id.license_plate, 'BB-777-BB')
        self.assertEqual(waybill.vehicle_id.company_id, self.company_b)

    def test_another_companys_car_is_not_linked_and_not_created_again(self):
        car_a = self.env['fleet.vehicle'].create({
            'license_plate': 'AA-555-AA', 'company_id': self.company_a.id,
            'model_id': self.env['fleet.vehicle']._ensure_rs_placeholder_model().id})
        waybill = self._b_waybill('AA-555-AA')
        self.assertFalse(waybill.vehicle_id)
        self.assertEqual(waybill.car_number, 'AA-555-AA', "RS.GE still gets the plate")
        self.assertEqual(self.env['fleet.vehicle'].with_context(active_test=False).search_count(
            [('license_plate', '=ilike', 'AA-555-AA')]), 1)
        self.assertEqual(car_a.company_id, self.company_a)

    def test_another_companys_contact_is_not_linked_as_driver(self):
        self.env['res.partner'].create({'name': 'A employee', 'vat': '01001000088',
                                        'company_id': self.company_a.id})
        waybill = self._b_waybill('BB-888-BB', tin='01001000088')
        self.assertFalse(waybill.driver_partner_id)
        self.assertEqual(waybill.driver_tin, '01001000088', "RS.GE still gets the TIN")
        self.assertEqual(self.env['res.partner'].search_count([('vat', '=', '01001000088')]), 1)

    def test_shared_driver_is_linked(self):
        shared = self.env['res.partner'].create({'name': 'Shared Driver', 'vat': '01001000099'})
        waybill = self._b_waybill('BB-999-BB', tin='01001000099')
        self.assertEqual(waybill.driver_partner_id, shared)
        self.assertTrue(shared.rs_is_driver)

    def test_transporter_name_lookup_uses_the_waybill_company_and_survives_rs_down(self):
        waybill = self.make_waybill(company_id=self.company_b.id, transport_type='7')
        service = type(self.env['rs.waybill.soap.service'])
        seen = []

        def lookup(svc, tin):
            seen.append(svc.env.company)
            return 'Transporter LLC'
        with patch.object(service, 'get_transporter_info', lookup):
            waybill.transporter_tin = '404040404'
            waybill._onchange_transporter_tin()
        self.assertEqual(waybill.transporter_name, 'Transporter LLC')
        self.assertEqual(seen, [self.company_b])

        waybill.transporter_name = False
        with patch.object(service, '_get_client', side_effect=ConnectionError("RS.GE down")):
            waybill.transporter_tin = '404040405'
            waybill._onchange_transporter_tin()
        self.assertFalse(waybill.transporter_name)
