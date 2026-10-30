# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from unittest.mock import patch

from odoo.addons.hr_payroll_account.tests.common import TestPayslipValidationCommon
from odoo.addons.l10n_be_hr_payroll.models.certificate import CertificateCertificate
from odoo.addons.l10n_be_hr_payroll.models.utils import xml_str_to_dict
from odoo.addons.l10n_be_hr_payroll.tests.common import TestBelgiumCommon

DRS_IGNORE_KEYS = (
    'FormCreationDate',
    'FormCreationHour',
    'ReferenceNbr',
    '@{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation',
)


class TestDRSCommon(TestPayslipValidationCommon, TestBelgiumCommon):

    @classmethod
    @TestPayslipValidationCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        cls.startClassPatcher(patch.object(
            CertificateCertificate, '_decode_certificate_for_be_onss_xml', lambda certificate, xml_str: b'dummy\r\nsignature\r\n'))

        cls.belgian_company = cls.company_data['company']
        cls.belgian_company.write({
            'vat': 'BE0897223670',
            'phone': '0471098765',
            'street': 'Test street',
            'city': 'Test city',
            'zip': '8292',
            'onss_expeditor_number': '123456',
            'country_id': cls.env.ref('base.be').id,
            'l10n_be_cbe_inscription': date(2000, 1, 1),
            'tz': 'Europe/Brussels',
        })
        cls.belgian_company.onss_certificate_id = cls.env['certificate.certificate'].create({})
        cls.belgian_company.current_payroll_config_id.write({
            'l10n_be_company_number': '0123456749',
            'l10n_be_revenue_code': '1234',
            'onss_registration_number': '125482497',
            'onss_importance_code': '4',
            'l10n_be_employer_category_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_employer_category_00010').id,
        })
        cls.env.user.write({'email': 'hr@example.com', 'phone': '+3221234567'})

        cls.calendar_38h = cls.env['resource.calendar'].create({
            'name': 'Standard 38 hours/week',
            'company_id': cls.belgian_company.id,
            'hours_per_day': 7.6,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour_from, 'hour_to': hour_to})
                for day in range(5) for hour_from, hour_to in ((8, 12), (13, 16.6))
            ],
        })
        cls.calendar_38h.reference_calendar_id = cls.calendar_38h
        cls.belgian_company.resource_calendar_id = cls.calendar_38h
        cls.calendar_19h = cls.env['resource.calendar'].create({
            'name': 'Part time 19 hours/week',
            'company_id': cls.belgian_company.id,
            'hours_per_day': 7.6,
            'reference_calendar_id': cls.calendar_38h.id,
            'attendance_ids': [(5, 0, 0)] + [
                (0, 0, {'dayofweek': str(day), 'hour_from': hour_from, 'hour_to': hour_to})
                for day, hour_from, hour_to in ((0, 8, 12), (0, 13, 16.6), (1, 8, 12), (1, 13, 16.6), (2, 8, 11.8))
            ],
        })

        cls.walloon_partner = cls.env['res.partner'].create({
            'name': 'Walloon Office',
            'street': 'Rue de la Loi',
            'city': 'Namur',
            'zip': '5000',
            'country_id': cls.env.ref('base.be').id,
        })
        cls.env['hr.work.location'].create({
            'name': 'Walloon Unit',
            'company_id': cls.belgian_company.id,
            'address_id': cls.walloon_partner.id,
            'location_type': 'dmfa_unit',
            'competence': 'wa',
            'bce_code': '2123456791',
        })
        cls.env['hr.work.entry.type']._update_payroll_related_fields(country_code='BE')
        cls.niss_sequence = 0

    @classmethod
    def _get_niss(cls, birthday):
        """ Valid NISS of a person born on `birthday` """
        cls.niss_sequence += 1
        base = f'{birthday:%y%m%d}{cls.niss_sequence * 2 + 1:03d}'
        check = 97 - int(('2' if birthday.year >= 2000 else '') + base) % 97
        return f'{base}{check:02d}'

    @classmethod
    def _create_drs_employee(cls, name, birthday=date(1990, 1, 1), **values):
        """ Belgian employee under contract since the 1st of January 2025, with an accepted Dimona """
        with patch.object(cls.env.registry['hr.version'], '_l10n_be_dimona_autodeclare'):
            employee = cls.env['hr.employee'].create({
                'name': name,
                'company_id': cls.belgian_company.id,
                'birthday': birthday,
                'niss': cls._get_niss(birthday),
                'lang': 'fr_BE',
                'tz': 'Europe/Brussels',
                'private_country_id': cls.env.ref('base.be').id,
                'hr_responsible_id': cls.env.user.id,
                'contract_date_start': date(2025, 1, 1),
                'date_version': date(2025, 1, 1),
                'resource_calendar_id': cls.calendar_38h.id,
                'structure_type_id': cls.env.ref('hr.structure_type_employee_cp200').id,
                'l10n_be_joint_committee_id': cls.env.ref('l10n_be_hr_payroll.l10n_be_joint_committee_200').id,
                'address_id': cls.walloon_partner.id,
                'wage': 2500.0,
                **values,
            })
        cls._create_dimona_period(employee)
        return employee

    @classmethod
    def _create_dimona_period(cls, employee, start_date='2025-01-01'):
        period = cls.env['l10n.be.dimona.period'].create({
            'name': f'6{employee.niss}',
            'company_id': cls.belgian_company.id,
            'content': {
                'periodId': f'6{employee.niss}',
                'worker': {'ssin': employee.niss},
                'startDate': start_date,
                'isCanceled': False,
                'isCanceledNsso': False,
                'lastDimonaType': 'in',
            },
        })
        cls.env.flush_all()
        period.employee_id = employee
        cls.env.flush_all()
        return period

    def _create_drs(self, employee, risk_xmlid, year, month, **values):
        risk = self.env.ref(f'l10n_be_hr_payroll.{risk_xmlid}')
        return self.env['l10n.be.drs'].create({
            'employee_id': employee.id,
            'sector': risk.sector,
            'risk_id': risk.id,
            'year': year,
            'month': str(month),
            **values,
        })

    def _create_validated_leave(self, employee, xmlid, date_from, date_to, approver=None, **values):
        leave_type = self.env.ref(f'hr_work_entry.{xmlid}')
        is_youth_holidays = leave_type.l10n_be_drs_nature == '3.4'
        if leave_type.requires_allocation and not (is_youth_holidays and self.env['hr.leave.allocation'].search_count([
                ('employee_id', '=', employee.id), ('work_entry_type_id', '=', leave_type.id)])):
            self.env['hr.leave.allocation'].create({
                'employee_id': employee.id,
                'work_entry_type_id': leave_type.id,
                # The youth and senior holidays can only be allocated once the legal holidays are taken
                'number_of_days': 20 if is_youth_holidays else (date_to - date_from).days + 1,
                'date_from': date(date_from.year, 1, 1),
            }).action_approve()
        leave = self.env['hr.leave'].with_context(leave_fast_create=True).create({
            'employee_id': employee.id,
            'work_entry_type_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
            **values,
        })
        leave.with_user(approver or self.env.user).action_approve()
        return leave

    def _get_declarations(self, employee, identification):
        return self.env['l10n.be.drs'].search([
            ('employee_id', '=', employee.id),
            ('identification', '=', identification),
        ], order='year, month')

    def _assertDRSEqual(self, drs_dict, ignore_keys=(), label=None):
        """ Compare the DRS dict with the JSON snapshot of the test
        (tests/test_files/drs/<test file>/<test method>.json), see
        TestPayrollBase._assert_dict_snapshot on how to (re)generate it. """
        self._assert_dict_snapshot(drs_dict, 'drs', label=label, ignore_keys=ignore_keys + DRS_IGNORE_KEYS)

    def _get_drs_dict(self, drs, skip_signature=True):
        """ Generate the declaration and return it as a dict """
        drs.with_context(onss_skip_signature=skip_signature).generate_declaration_xml_report()
        self.assertFalse(drs.error_message)
        self.assertEqual(drs.state, 'ready')
        return xml_str_to_dict(drs.xml_file.content)

    def _notify_drs(self, drs, ticket, accepted=True):
        """ Process the notification of the ONSS about the declaration `drs`, sent with its ticket """
        if not drs.xml_file:
            self._get_drs_dict(drs)
        onss_declaration = drs.create_onss_declaration()
        notification = f"""<?xml version="1.0" encoding="UTF-8"?>
<NOTIFICATION xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="NOTIFICATION_20263.xsd">
    <Form>
        <Identification>NOTI001</Identification>
        <FormCreationDate>2026-10-20</FormCreationDate>
        <FormCreationHour>10:00:00.000</FormCreationHour>
        <AttestationStatus>0</AttestationStatus>
        <TypeForm>FA</TypeForm>
        <FileReference>
            <FileName>{drs.xml_filename}</FileName>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>3400001Y1P01G</ReferenceNbr>
        </FileReference>
        <HandledOriginalForm>
            <Identification>{drs.identification}</Identification>
            <FormCreationDate>2026-10-20</FormCreationDate>
            <FormCreationHour>09:00:00.000</FormCreationHour>
            <AttestationStatus>0</AttestationStatus>
            <TypeForm>SU</TypeForm>
        </HandledOriginalForm>
        <HandledReference>
            <ReferenceType>1</ReferenceType>
            <ReferenceOrigin>2</ReferenceOrigin>
            <ReferenceNbr>{ticket}</ReferenceNbr>
        </HandledReference>
        <HandlingResult>
            <ResultCode>{1 if accepted else 0}</ResultCode>
        </HandlingResult>
    </Form>
</NOTIFICATION>"""
        sequence = drs.xml_filename.split('.')[4]
        self.env['l10n.be.onss.declaration']._process_incoming_onss_files([
            (f'FO.NOTI.123456.20261020.{sequence}.R.1', notification.encode()),
        ])
        return onss_declaration
