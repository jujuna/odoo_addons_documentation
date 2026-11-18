
from unittest.mock import patch

from odoo.tests import Form, tagged
from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'payroll_payslip_with_dmfa_languages')
class TestPayrollPayslipWithDmfaLanguages(TestPayrollCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create a L10n_BeDmfaLocationUnit
        working_address = cls.env['res.partner'].create({'name': 'Working Address'})
        # Activate French and Dutch
        cls.env['res.lang']._activate_lang('fr_BE')
        cls.env['res.lang']._activate_lang('nl_BE')
        cls.env['res.lang']._activate_lang('de_DE')

        cls.work_location = cls.env['hr.work.location'].create({
            'bce_code': '8888888770',
            'location_type': 'dmfa_unit',
            'company_id': cls.belgian_company.id,
            'address_id': working_address.id,
            'competence': 'fl',
            'payslip_language_id': cls.env['res.lang']._lang_get('nl_BE').id,
        })

        cls.employee_georges.address_id = working_address.id
        cls.employee_georges.version_id.work_location_id = cls.work_location
        cls.env.user.lang = 'en_US'

        cls.payslip = cls.env['hr.payslip'].create({
            'name': "Payslip",
            'employee_id': cls.employee_georges.id,
            'version_id': cls.employee_georges.version_id.id,
        })

    def assert_payslip_languages(self, competence, location_lang, employee_lang, expected):
        self.work_location.write({
            'competence': competence,
            'payslip_language_id': self.env['res.lang']._lang_get(location_lang).id,
        })
        self.employee_georges.lang = employee_lang
        self.env.invalidate_all()

        self.assertEqual(
            self.payslip._get_payslips_pdf_lang()[self.payslip], expected,
            f"{competence} work location ({location_lang}), employee language: {employee_lang}")

    def test_payslip_with_dmfa_languages(self):
        # Flanders, Wallonia and the german speaking area have a single legal language.
        self.assert_payslip_languages('fl', 'nl_BE', 'nl_BE', ('nl_BE', None))
        self.assert_payslip_languages('fl', 'nl_BE', 'fr_BE', ('nl_BE', 'fr_BE'))
        self.assert_payslip_languages('wa', 'fr_BE', 'fr_BE', ('fr_BE', None))
        self.assert_payslip_languages('wa', 'fr_BE', 'nl_BE', ('fr_BE', 'nl_BE'))
        self.assert_payslip_languages('cg', 'de_DE', 'de_DE', ('de_DE', None))
        self.assert_payslip_languages('cg', 'de_DE', 'fr_BE', ('de_DE', 'fr_BE'))

        # Brussels is bilingual: an employee speaking either national language gets the payslip in that one
        self.assert_payslip_languages('br', 'nl_BE', 'nl_BE', ('nl_BE', None))
        self.assert_payslip_languages('br', 'nl_BE', 'fr_BE', ('fr_BE', None))
        self.assert_payslip_languages('br', 'nl_BE', 'en_US', ('nl_BE', 'en_US'))
        self.assert_payslip_languages('br', 'fr_BE', 'fr_BE', ('fr_BE', None))
        self.assert_payslip_languages('br', 'fr_BE', 'nl_BE', ('nl_BE', None))
        self.assert_payslip_languages('br', 'fr_BE', 'de_DE', ('fr_BE', 'de_DE'))

        self.assert_payslip_languages('fl', 'nl_BE', False, ('nl_BE', None))

        # Without payslip language, the legal language is the one of the language region of the location
        self.assert_payslip_languages('fl', False, 'en_US', ('nl_BE', 'en_US'))
        self.assert_payslip_languages('wa', False, 'en_US', ('fr_BE', 'en_US'))
        self.assert_payslip_languages('cg', False, 'fr_BE', ('de_DE', 'fr_BE'))
        self.assert_payslip_languages('br', False, 'nl_BE', ('nl_BE', None))
        self.assert_payslip_languages('br', False, 'en_US', ('fr_BE', 'en_US'))

    def test_payslip_language_fallback_on_dmfa_unit(self):
        """A work location without payslip language falls back on the DMFA unit of the version address."""
        office = self.env['hr.work.location'].create({
            'name': 'Office without language',
            'location_type': 'office',
            'company_id': self.belgian_company.id,
            'address_id': self.belgian_company.partner_id.id,
        })
        self.employee_georges.version_id.work_location_id = office
        self.employee_georges.lang = 'en_US'
        self.assertEqual(self.employee_georges.version_id.l10n_be_location_unit, self.work_location)
        self.assertEqual(self.payslip._get_payslips_pdf_lang()[self.payslip], ('nl_BE', 'en_US'))

        warning = self.env.ref('l10n_be_hr_payroll.hr_payroll_warning_invalid_lang').with_company(self.belgian_company)
        self.assertNotIn(office, warning._get_warning_python_records({})[0])
        self.work_location.payslip_language_id = False
        self.assertIn(office, warning._get_warning_python_records({})[0])
        # the language region of the DMFA unit (Flanders) still gives the legal language
        self.assertEqual(self.payslip._get_payslips_pdf_lang()[self.payslip], ('nl_BE', 'en_US'))
        self.work_location.competence = False
        self.assertEqual(self.payslip._get_payslips_pdf_lang()[self.payslip], ('en_US', None))

    def test_translated_payslip_pdf(self):
        self.employee_georges.lang = 'en_US'
        languages = self.payslip._get_payslips_pdf_lang()[self.payslip]
        self.assertEqual(languages, ('nl_BE', 'en_US'))

        report = self.env.ref('l10n_be_hr_payroll.action_report_payslip_be')
        calls = []

        def _generate_payslip_pdf(payslip, lang, report, translated_from=False):
            calls.append((lang, translated_from))
            return b''

        with patch.object(self.registry['hr.payslip'], '_generate_payslip_pdf', _generate_payslip_pdf), \
                patch('odoo.tools.pdf.merge_pdf', b''.join):
            self.payslip._prepare_payslip_pdf_content(report, languages)
        self.assertEqual(calls, [('nl_BE', False), ('en_US', 'nl_BE')])

        def render(**context):
            return self.env['ir.actions.report'].with_context(lang='en_US', **context)._render_qweb_html(
                report.report_name, self.payslip.ids)[0].decode()

        dutch = self.env['res.lang']._lang_get('nl_BE').with_context(lang='en_US').name
        html = render()
        self.assertIn('This payslip is draft. This is not a legal document.', html)
        self.assertNotIn('This document is a translation', html)
        html = render(translated_from='nl_BE')
        self.assertIn(f'This document is a translation, only the original {dutch} document holds legal value.', html)
        self.assertIn('This payslip is not validated.', html, "The translation of a draft payslip still says it is not validated")

    def test_set_missing_location_language(self):
        """A location with a competence but without payslip language (e.g. created before the language was saved
        from the form) must be fixable from the form."""
        location = self.env['hr.work.location'].create({
            'name': 'Flemish Office',
            'location_type': 'office',
            'company_id': self.belgian_company.id,
            'address_id': self.belgian_company.partner_id.id,
            'competence': 'fl',
        })
        self.assertFalse(location.payslip_language_id)
        with Form(location) as location_form:
            location_form.payslip_language_id = self.env['res.lang']._lang_get('nl_BE')
        self.assertEqual(location.payslip_language_id.code, 'nl_BE')
