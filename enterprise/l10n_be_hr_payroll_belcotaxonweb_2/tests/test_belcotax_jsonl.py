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
        # The company car benefit stays within the commuting exemption of box 14c: only the internet is in box 6b
        self.assertEqual(fiche['2099'], ['I'])
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

    def test_correction_follows_the_corrected_fiches(self):
        original = self._create_declaration()
        original_fiche = self._fiche(self._generate(original))
        original.reference = 'BOW-1'
        original.with_context(skip_validation=True).action_mark_as_done()
        # A fiche sent by the original declaration for an employee who isn't declared anymore
        former_employee = self.env['hr.employee'].create({'name': 'Former Employee', 'company_id': self.belgian_company.id})
        sheet = original.l10n_be_281_10_ids
        sheet.line_ids = [(0, 0, {
            'employee_id': former_employee.id,
            'company_id': self.belgian_company.id,
            'res_model': sheet._name,
            'res_id': sheet.id,
        })]

        correction = original.browse(original.action_correct_declaration()['res_id'])
        documents = self._generate(correction)
        self.assertEqual(self._fiche(documents)['2205'], '3')
        former_key = original._get_belcotax_fiche_key('281.10', former_employee)
        self.assertIn({'$s': 'urn:f:x:1', 'k': former_key}, documents, "The fiche of the former employee is cancelled")
        self.assertNotIn(f'{original._get_belcotax_key_prefix()}_P{former_employee.id}', [document['k'] for document in documents])

        # The fiche of an employee who wasn't in the corrected declaration is an original fiche
        correction.action_set_draft_declaration()
        sheet.line_ids.filtered(lambda line: line.employee_id == self.employee).unlink()
        documents = self._generate(correction)
        self.assertEqual(self._fiche(documents)['k'], original_fiche['k'])
        self.assertNotIn('2205', self._fiche(documents))

        # The cancellation deletes all the fiches of the corrected declaration
        correction.action_set_draft_declaration()
        correction.type_treatment = '3'
        deleted_keys = {document['k'] for document in self._generate(correction) if document['$s'] == 'urn:f:x:1'}
        self.assertEqual(deleted_keys, {original_fiche['k'], former_key})

    def test_person_without_niss(self):
        self.employee.write({'niss': '/', 'birthday': date(1985, 1, 1), 'place_of_birth': 'Paris'})
        person = self._generate(self._create_declaration())[2]
        self.assertNotIn('i', person)
        self.assertEqual((person['bd'], person['bp']), ('1985-01-01', 'Paris'))

    def test_person_without_niss_requires_birth_date(self):
        self.employee.write({'niss': '/', 'birthday': False})
        declaration = self._create_declaration()
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'error')
        self.assertFalse(declaration.xml_file)
        self.assertIn('Declaration Employee has no national number', declaration.error_message)
        line = declaration.l10n_be_281_10_line_ids.filtered(lambda line: line.employee_id == self.employee)
        self.assertIn('birth date is required on the 281.10 form', line.declaration_error)
        self.assertEqual(declaration.forms_with_error, '281.10')

        # The deletion of the fiche only needs its key
        declaration.action_set_draft_declaration()
        declaration.write({'type_sending': '1', 'type_treatment': '3'})
        self.assertEqual(self._generate(declaration)[-1]['$s'], belcotax_schema.DELETE_FICHE_SCHEMA)

        declaration.action_set_draft_declaration()
        declaration.write({'type_sending': '0', 'type_treatment': '0'})
        self.employee.birthday = date(1985, 1, 1)
        self._generate(declaration)
        self.assertFalse(declaration.forms_with_error)

    def test_identification_errors(self):
        declaration = self._create_declaration()
        self.assertFalse(declaration._get_belcotax_identification_errors('281.20', self.employee), "The NISS is enough")
        self.employee.write({'niss': '/', 'birthday': False})
        self.assertTrue(declaration._get_belcotax_identification_errors('281.10', self.employee))
        self.assertFalse(declaration._get_belcotax_identification_errors('281.30', self.employee))
        # 281.20: a Belgian resident has a national number, a foreign one is identified by their birth date
        self.assertIn('national or BIS number', declaration._get_belcotax_identification_errors('281.20', self.employee)[0])
        self.employee.write({'private_country_id': self.env.ref('base.fr').id, 'private_zip': '75001', 'private_city': 'Paris'})
        self.assertIn('birth date', declaration._get_belcotax_identification_errors('281.20', self.employee)[0])
        self.employee.birthday = date(1985, 1, 1)
        self.assertFalse(declaration._get_belcotax_identification_errors('281.20', self.employee))

    def _get_warning_records(self, xmlid):
        self.env.flush_all()
        warning = self.env.ref(xmlid)
        results = self.env['hr.payroll.warning']._get_applicable_payroll_warnings(self.belgian_company)
        return self.env['hr.employee'].union(result['records'] for result in results if result['warning'] == warning)

    def test_identification_warnings(self):
        no_niss_xmlid = 'l10n_be_hr_payroll_belcotaxonweb_2.hr_payroll_warning_281_no_national_number'
        identification_xmlid = 'l10n_be_hr_payroll_belcotaxonweb_2.hr_payroll_warning_281_incomplete_identification'
        self.assertNotIn(self.employee, self._get_warning_records(no_niss_xmlid))
        self.assertNotIn(self.employee, self._get_warning_records(identification_xmlid))
        self.employee.write({'niss': '/', 'private_city': False})
        self.assertIn(self.employee, self._get_warning_records(no_niss_xmlid))
        self.assertIn(self.employee, self._get_warning_records(identification_xmlid))

    def test_schema_errors_name_the_employee(self):
        self.employee.private_street = 'Rue ' * 30
        declaration = self._create_declaration()
        with freeze_time('2026-02-01'):
            declaration.action_generate_xml()
        self.assertEqual(declaration.state, 'error')
        self.assertIn('Declaration Employee', declaration.error_message)
        self.assertIn('/a/s', declaration.error_message)

    def test_option_percentages(self):
        declaration = self._create_declaration()
        schema = belcotax_schema.get_fiche_schemas(2025)['281.10']
        for value, expected in (
            ('00,00', [Decimal('0')]),
            ('15,00:23,00', [Decimal('0.15'), Decimal('0.23')]),
            ('', None),
        ):
            zones, errors = declaration._get_belcotax_zones('281.10', schema, {'f10_2106_percentages': value})
            self.assertFalse(errors)
            self.assertEqual([item['2106'] for item in zones['4220']] if expected is not None else zones.get('4220'), expected)
        _zones, errors = declaration._get_belcotax_zones('281.10', schema, {'f10_2106_percentages': '15,00:abc'})
        self.assertEqual(len(errors), 1)

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
