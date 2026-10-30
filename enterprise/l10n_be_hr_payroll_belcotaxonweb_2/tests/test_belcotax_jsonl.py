# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
from datetime import date, datetime
from decimal import Decimal

from freezegun import freeze_time
from lxml import etree
from stdnum.be.vat import compact as vat_be_compact

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.l10n_be_hr_payroll.tests.common import TestPayrollCommon
from odoo.addons.l10n_be_hr_payroll_belcotaxonweb_2.models import belcotax_schema


@tagged('post_install_l10n', 'post_install', '-at_install', 'belcotaxonweb_2')
class TestBelcotaxJsonl(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Audi'})
        car_model = cls.env['fleet.vehicle.model'].create({'name': 'A3', 'brand_id': brand.id})
        with freeze_time('2025-01-01'):
            cls.employee = cls.create_employee({
                'name': 'Declaration Employee',
                'date_version': date(2025, 1, 1),
                'contract_date_start': date(2025, 1, 1),
                'niss': '85010100115',
                'private_street': 'Rue du Test 1',
                'private_zip': '1000',
                'private_city': 'Brussels',
                'l10n_be_legal_first_name': 'Jean Pierre',
                'l10n_be_legal_last_name': 'Van den Berg',
                'internet': 38.0,
            })
            car = cls.env['fleet.vehicle'].create({
                'model_id': car_model.id,
                'company_id': cls.belgian_company.id,
                'atn': 2400.0,
                'driver_employee_id': cls.employee.id,
            })
            cls.employee.version_id.write({'transport_mode_car': True, 'car_id': car.id})
        with freeze_time('2025-04-15'):
            cls.create_and_validate_payslips(cls.employee, 2025, [1, 2, 3])
        cls.env.user.email = 'payroll@example.com'

    def _create_declaration(self, file_format='jsonl', **values):
        with freeze_time('2026-02-01'):
            return self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
                'year': '2025',
                'company_id': self.belgian_company.id,
                'file_format': file_format,
                **values,
            })

    def _generate(self, declaration):
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'ready', declaration.error_message)
        return [json.loads(line, parse_float=Decimal) for line in bytes(declaration.xml_file).decode().splitlines()]

    def _fiche(self, documents, form='10'):
        fiches = [document for document in documents if document['$s'].startswith(f'urn:f:d:2025:{form}:')]
        self.assertEqual(len(fiches), 1)
        return fiches[0]

    def test_file_format_by_year(self):
        declaration = self._create_declaration(file_format='xml')
        self.assertEqual(declaration.file_format, 'xml')
        self.assertEqual(self.env['l10n_be.281_xx'].create({'year': '2026'}).file_format, 'jsonl')
        with self.assertRaises(ValidationError):
            self.env['l10n_be.281_xx'].create({'year': '2026', 'file_format': 'xml'})

    def test_missing_schemas(self):
        declaration = self.env['l10n_be.281_xx'].create({'year': '2026'})
        with self.assertRaisesRegex(UserError, 'not available yet'):
            declaration._get_belcotax_fiche_schemas()

    def test_resources(self):
        declaration = self._create_declaration()
        documents = self._generate(declaration)
        self.assertEqual(declaration.xml_filename, '2025_281.jsonl')
        contact, debtor, person = documents[:3]
        bce = vat_be_compact(self.belgian_company.vat)
        self.assertEqual(contact, {
            '$s': 'urn:r:d:c:1',
            'k': f'{bce}_C{self.env.user.id}',
            'e': 'payroll@example.com',
            'l': contact['l'],
            **({'p': contact['p']} if 'p' in contact else {}),
        })
        self.assertIn(contact['l'], ('fr', 'nl', 'de'))
        self.assertEqual(debtor['$s'], 'urn:r:d:o:1')
        self.assertEqual(debtor['i'], {'cbein': bce})
        self.assertEqual(debtor['a']['l'], '150')
        self.assertEqual(person, {
            '$s': 'urn:r:d:p:1',
            'k': f'{bce}_P{self.employee.id}',
            'i': {'ssin': '85010100115'},
            'fn': ['Jean Pierre'],
            'ln': ['Van den Berg'],
            'a': {'s': 'Rue du Test 1', 'p': '1000', 'c': 'Brussels', 'l': '150'},
        })
        keys = [document['k'] for document in documents]
        self.assertEqual(len(keys), len(set(keys)), "The keys must be unique in the file")

        fiche = self._fiche(documents)
        self.assertEqual(fiche['k'], f'{bce}_2025_28110_{self.employee.id}')
        self.assertEqual((fiche['b'], fiche['c'], fiche['d']), (person['k'], contact['k'], debtor['k']))

    def test_fiche_matches_the_xml_file(self):
        fiche = self._fiche(self._generate(self._create_declaration()))
        xml_declaration = self._create_declaration(file_format='xml')
        with freeze_time('2026-02-01'):
            xml_declaration.action_generate_xml()
        self.assertEqual(xml_declaration.state, 'ready', xml_declaration.error_message)
        xml_fiche = etree.fromstring(bytes(xml_declaration.xml_file)).find('.//Fiche28110')
        xml_zones = {element.tag.split('_')[1]: element.text for element in xml_fiche if element.tag.startswith('f10_')}

        zone_schemas = belcotax_schema.get_fiche_schemas(2025)['281.10']['properties']
        for zone, value in fiche.items():
            if not zone[0].isdigit():
                continue
            zone_schema = zone_schemas[zone]
            if zone_schema.get('unit') in ('euro', 'hour'):
                self.assertEqual(round(value * 100), int(xml_zones[zone]), zone)
            elif zone_schema.get('format') == 'date':
                self.assertEqual(value, datetime.strptime(xml_zones[zone], '%d-%m-%Y').date().isoformat(), zone)
            elif zone == '2099':
                self.assertEqual(''.join(value), xml_zones[zone])
            else:
                self.assertEqual(value, xml_zones[zone], zone)
        for zone, value in xml_zones.items():
            if zone not in fiche and zone in zone_schemas and not zone_schemas[zone].get('readOnly'):
                self.assertIn(value, ('0', '', None), f"The zone {zone} is missing from the JSON fiche")

        self.assertGreater(fiche['2060'], 0)
        self.assertGreater(fiche['2088'], 0)
        self.assertIn('F', fiche['2099'])
        self.assertGreater(fiche['2131'], 0)
        for computed_zone in ('2062', '2074', '2077', '2059', '5100'):
            self.assertNotIn(computed_zone, fiche, "Belcotax-on-web computes the totals")
        self.assertNotIn('2205', fiche, "The zone 2205 of an original fiche is empty")
        self.assertFalse([zone for zone, value in fiche.items() if value in (0, '0')], "Empty zones are left out")

    def test_correction_and_cancellation(self):
        original = self._create_declaration()
        original_fiche = self._fiche(self._generate(original))
        original.reference = 'BOW-1'
        original.with_context(skip_validation=True).action_mark_as_done()

        correction = original.browse(original.action_correct_declaration()['res_id'])
        correction_fiche = self._fiche(self._generate(correction))
        self.assertEqual(correction_fiche['k'], original_fiche['k'], "A correction replaces the fiche with the same key")
        self.assertEqual(correction_fiche['2205'], '3')
        self.assertEqual(correction_fiche['2060'], original_fiche['2060'], "All the zones of the fiche are sent again")

        correction.action_set_draft_declaration()
        correction.type_treatment = '3'
        documents = self._generate(correction)
        self.assertIn({'$s': 'urn:f:x:1', 'k': original_fiche['k']}, documents)
        self.assertFalse([document for document in documents if document['$s'].startswith('urn:f:d:')])

    def test_person_without_niss(self):
        self.employee.write({'niss': '/', 'birthday': date(1985, 1, 1), 'place_of_birth': 'Paris'})
        person = self._generate(self._create_declaration())[2]
        self.assertNotIn('i', person)
        self.assertEqual((person['bd'], person['bp']), ('1985-01-01', 'Paris'))

    def test_schema_errors_name_the_employee(self):
        self.employee.private_street = 'Rue ' * 30
        declaration = self._create_declaration()
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'error')
        self.assertIn('Declaration Employee', declaration.error_message)
        self.assertIn('/a/s', declaration.error_message)

    def test_validator(self):
        amount = {'type': 'number', 'minimum': 0, 'multipleOf': Decimal('0.01')}
        self.assertFalse(belcotax_schema.validate(amount, Decimal('0.29')))
        self.assertTrue(belcotax_schema.validate(amount, Decimal('0.295')))
        self.assertTrue(belcotax_schema.validate(amount, Decimal('-1')))
        self.assertTrue(belcotax_schema.validate(amount, '1'))
        enum = {'type': 'string', 'oneOf': [{'const': '0'}, {'const': '1'}]}
        self.assertFalse(belcotax_schema.validate(enum, '1'))
        self.assertTrue(belcotax_schema.validate(enum, '2'))
        fiche_schema = belcotax_schema.get_fiche_schemas(2025)['281.10']
        self.assertTrue(belcotax_schema.validate(fiche_schema, {'$s': 'urn:f:d:2025:10:1203', 'k': 'a', 'c': 'b', 'd': 'c', '9999': 1}))
