# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from stdnum.be.vat import compact as vat_be_compact

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import BinaryBytes

from odoo.addons.l10n_be_hr_payroll.models.l10n_be_281_XX import COUNTRY_CODES, REPORT_CONFIG
from odoo.addons.l10n_be_hr_payroll_belcotaxonweb_2.models import belcotax_schema

# From the income year 2026, Belcotax-on-web only accepts JSON Lines files.
# https://finances.belgium.be/fr/E-services/Belcotaxonweb/documentation-technique/faq-bow-2
JSONL_MANDATORY_YEAR = 2026
# Zones of the XML forms that the JSON fiches don't have: the control totals (2059) and data moved to the
# resources: the fiscal identification number (2109) and the nature of the beneficiary (2030), given by the
# type of its resource.
XML_ONLY_ZONES = {
    '281.10': {'2059', '2109', '2257'},
    '281.13': {'2059', '2109'},
    '281.18': {'2059', '2109'},
    '281.20': {'2059', '2109', '2045', '2055', '2056'},
    '281.30': {'2059', '2109', '2030'},
    '281.45': {'2059', '2109', '2030', '2110'},
}
# The "other codes" (code, amount) of the XML forms are the items of the zone 4020 of the JSON fiches
OTHER_CODE_ZONES = [('2092', '2185'), ('2094', '2186'), ('2096', '2187'), ('2098', '2188')]


class L10n_Be281_XX(models.Model):
    _inherit = 'l10n_be.281_xx'

    file_format = fields.Selection([
        ('xml', 'XML'),
        ('jsonl', 'JSON Lines'),
    ], compute='_compute_file_format', store=True, readonly=False, required=True, precompute=True,
        help="Belcotax-on-web only accepts JSON Lines files from the income year 2026. For the previous income "
             "years, JSON Lines files can be sent as test sendings to the new version of Belcotax-on-web.")

    @api.depends('year')
    def _compute_file_format(self):
        for declaration in self:
            declaration.file_format = 'jsonl' if int(declaration.year) >= JSONL_MANDATORY_YEAR else 'xml'

    @api.constrains('year', 'file_format')
    def _check_file_format(self):
        for declaration in self:
            if declaration.file_format == 'xml' and int(declaration.year) >= JSONL_MANDATORY_YEAR:
                raise ValidationError(self.env._(
                    "From the income year %s, Belcotax-on-web only accepts JSON Lines files.", JSONL_MANDATORY_YEAR))

    def _generate_281_xml(self, is_test=False):
        super()._generate_281_xml(is_test=is_test)
        if self.file_format == 'jsonl':
            if is_test and self.test_xml_file:
                self.test_xml_filename = f"TEST_{self.year}_281.jsonl"
            elif not is_test and self.xml_file:
                self.xml_filename = f"{self.year}_281.jsonl"

    def _render_xml(self, is_test=False):
        if self.file_format == 'jsonl':
            return self._render_jsonl()
        return super()._render_xml(is_test=is_test)

    def _validate_xml_content(self, file_content, success_state):
        if self.file_format == 'jsonl':
            # Each document is validated against its schema while rendering, to name the employee in the errors
            self.error_message = False
            self.state = success_state
            return
        super()._validate_xml_content(file_content, success_state)

    def _get_belcotax_fiche_schemas(self):
        self.ensure_one()
        schemas = belcotax_schema.get_fiche_schemas(int(self.year))
        if not schemas:
            raise UserError(self.env._(
                "The Belcotax-on-web schemas of the income year %s are not available yet. "
                "Please update Odoo once they are published by the FPS Finance.", self.year))
        return schemas

    @api.model
    def _get_belcotax_country_code(self, country):
        # Code INS of the country, without the 2 leading zeroes of the XML files
        return '150' if country.code == 'BE' else COUNTRY_CODES[country.code][-3:]

    @api.model
    def _get_belcotax_address(self, street, zip_code, city, country, number=False, box=False):
        address = {'s': street, 'n': number, 'b': box, 'p': zip_code, 'c': city, 'l': self._get_belcotax_country_code(country)}
        return {key: value.strip() for key, value in address.items() if value and value.strip()}

    def _get_belcotax_key_prefix(self):
        # The keys are unique for a sender, whatever the income year: the sender may send for several companies
        return vat_be_compact(self.company_id.vat)

    def _get_belcotax_contact(self):
        user = self.env.user
        if not user.email:
            raise UserError(self.env._(
                "Your user must have an email address: it is the contact of the sending in Belcotax-on-web."))
        lang = (user.lang or '')[:2]
        contact = {
            '$s': belcotax_schema.CONTACT_SCHEMA,
            'k': f'{self._get_belcotax_key_prefix()}_C{user.id}',
            'e': user.email,
            'l': lang if lang in ('fr', 'nl', 'de') else 'fr',
        }
        employee = user.employee_id
        if employee.l10n_be_legal_first_name and employee.l10n_be_legal_last_name:
            contact['fn'] = [employee.l10n_be_legal_first_name]
            contact['ln'] = [employee.l10n_be_legal_last_name]
        phone = self.company_id._phone_format(number=self.company_id.phone, force_format='E164')
        if phone:
            contact['p'] = {'l': phone}
        return contact

    def _get_belcotax_debtor(self):
        company = self.company_id
        partner = company.partner_id
        street_name = partner.street_name if 'street_name' in partner else False
        return {
            '$s': belcotax_schema.ORGANISATION_SCHEMA,
            'k': f'{self._get_belcotax_key_prefix()}_O{company.id}',
            'i': {'cbein': vat_be_compact(company.vat)},
            # A company has the same legal name in every language
            'n': {lang: company.name for lang in ('fr', 'nl', 'de')},
            'a': self._get_belcotax_address(
                street_name or company.street, company.zip, company.city, company.country_id,
                number=street_name and partner.street_number, box=street_name and partner.street_number2),
        }

    def _get_belcotax_person(self, employee):
        person = {
            '$s': belcotax_schema.PERSON_SCHEMA,
            'k': f'{self._get_belcotax_key_prefix()}_P{employee.id}',
            'fn': [employee.l10n_be_legal_first_name],
            'ln': [employee.l10n_be_legal_last_name],
            'a': self._get_belcotax_address(
                ' '.join(filter(None, [employee.private_street, employee.private_street2])),
                employee.private_zip, employee.private_city, employee.private_country_id),
        }
        if employee.niss and employee.niss != '/':
            person['i'] = {'ssin': employee.niss}
        else:
            # Without a national number, the person is identified by its birth date and place
            if employee.birthday:
                person['bd'] = employee.birthday.isoformat()
            if employee.place_of_birth:
                person['bp'] = employee.place_of_birth
        return person

    def _get_belcotax_fiche_key(self, report_key, employee):
        # The same key for the corrections of the fiche: Belcotax-on-web replaces the fiche with the same key
        return f'{self._get_belcotax_key_prefix()}_{self.year}_{report_key.replace(".", "")}_{employee.id}'

    @api.model
    def _is_belcotax_empty(self, value):
        # Empty zones are left out: a 0 can have another meaning than an empty zone in Belcotax-on-web
        if isinstance(value, str):
            return not value.strip('0 ')
        return not value

    @api.model
    def _get_belcotax_zone_value(self, zone_schema, value):
        zone_type = zone_schema.get('type')
        if zone_type == 'number':
            step = zone_schema.get('multipleOf', Decimal('0.01'))
            # Decimal(str()) for the amounts like 0.29, which are 0.28999... as floats
            return round(float(value)) if step >= 1 else Decimal(str(value)).quantize(step)
        if zone_type == 'string':
            if zone_schema.get('format') == 'date':
                return value.isoformat() if isinstance(value, date) else datetime.strptime(value, '%d-%m-%Y').date().isoformat()
            return str(value)
        if zone_type == 'array':
            # Nature of the benefits in kind: 'BFH' -> ['B', 'F', 'H']
            return list(dict.fromkeys(str(value)))
        raise UserError(self.env._("Unsupported Belcotax-on-web zone type %s", zone_type))

    def _get_belcotax_zones(self, report_key, schema, employee_data):
        """Convert the values of the XML zones of a form into the zones of its JSON fiche.

        :return: tuple (zones, errors)
        """
        zone_schemas = schema['properties']
        values = {}
        for tag, value in employee_data.items():
            # Only the zones of the form: the common ones (name, address...) are in the resources
            match = re.fullmatch(r'f\d+_(\d{4})_\w+', tag)
            if match:
                values[match[1]] = value

        zones = {}
        errors = []
        if '4020' in zone_schemas:
            other_codes = []
            for code_zone, amount_zone in OTHER_CODE_ZONES:
                code, amount = values.pop(code_zone, False), values.pop(amount_zone, 0)
                if not self._is_belcotax_empty(code):
                    other_codes.append({
                        '2092': str(code).zfill(3),
                        '2185': self._get_belcotax_zone_value({'type': 'number'}, amount),
                    })
            if other_codes:
                zones['4020'] = other_codes
        if '4220' in zone_schemas and '2106' in values:
            # The percentages of the options on shares, like '00,00' in the XML files, are fractions of 1
            percentages = values.pop('2106')
            if percentages and str(percentages).strip():
                zones['4220'] = [{'2106': (Decimal(str(percentages).replace(',', '.')) / 100).quantize(Decimal('0.0001'))}]

        for zone, value in values.items():
            zone_schema = zone_schemas.get(zone)
            if zone_schema is None:
                if zone not in XML_ONLY_ZONES.get(report_key, set()) and not self._is_belcotax_empty(value):
                    errors.append(self.env._("the zone %(zone)s doesn't exist in Belcotax-on-web", zone=zone))
                continue
            # The totals are computed by Belcotax-on-web
            if zone_schema.get('readOnly') or self._is_belcotax_empty(value):
                continue
            try:
                zones[zone] = self._get_belcotax_zone_value(zone_schema, value)
            except (ValueError, TypeError, ArithmeticError):
                errors.append(self.env._("the value %(value)s of the zone %(zone)s is invalid", value=value, zone=zone))
        return zones, errors

    def _get_belcotax_schema_errors(self, schema, document):
        # Validated as it would be read back from the file
        return belcotax_schema.validate(schema, json.loads(self._dump_belcotax_document(document), parse_float=Decimal))

    @api.model
    def _dump_belcotax_document(self, document):
        # The amounts in euros, with a dot as decimal separator
        return json.dumps(document, ensure_ascii=False, default=lambda value: float(value) if isinstance(value, Decimal) else str(value))

    def _get_belcotax_documents(self):
        """:return: tuple (documents, errors), the resources being before the fiches that reference them"""
        self.ensure_one()
        self._check_company_configuration()
        fiche_schemas = self._get_belcotax_fiche_schemas()
        resource_schemas = belcotax_schema.get_resource_schemas()
        contact = self._get_belcotax_contact()
        debtor = self._get_belcotax_debtor()
        errors = []
        for label, document in ((self.env._("Contact"), contact), (self.company_id.name, debtor)):
            errors += [f"- {label}: {error}" for error in self._get_belcotax_schema_errors(resource_schemas[document['$s']], document)]

        persons = {}
        fiches = []
        for report_key, config in REPORT_CONFIG.items():
            if not (self[config['include_field']] and self[config['count_field']]):
                continue
            if report_key not in fiche_schemas:
                raise UserError(self.env._(
                    "The Belcotax-on-web schema of the form %(form)s for the income year %(year)s is not available.",
                    form=report_key, year=self.year))
            report = self[config['relation_field']]
            result = report._get_rendering_data(report.line_ids.employee_id)
            errors += [f"- {message}" for message in result['employees_with_error'].values()]
            schema = fiche_schemas[report_key]
            for employee_data in result['employees_data']:
                employee = employee_data['employee']
                label = f"{report_key} {employee.name}"
                if employee not in persons:
                    persons[employee] = self._get_belcotax_person(employee)
                    errors += [
                        f"- {employee.name}: {error}"
                        for error in self._get_belcotax_schema_errors(resource_schemas[belcotax_schema.PERSON_SCHEMA], persons[employee])
                    ]
                key = self._get_belcotax_fiche_key(report_key, employee)
                if self.type_sending == '1' and self.type_treatment == '3':
                    fiches.append({'$s': belcotax_schema.DELETE_FICHE_SCHEMA, 'k': key})
                    continue
                zones, zone_errors = self._get_belcotax_zones(report_key, schema, employee_data)
                fiche = {
                    '$s': belcotax_schema.get_schema_id(schema),
                    'k': key,
                    'b': persons[employee]['k'],
                    'c': contact['k'],
                    'd': debtor['k'],
                    **zones,
                }
                # A corrective fiche replaces the original one, all its zones are filled again
                if self.type_sending == '1' and self.type_treatment == '1' and '2205' in schema['properties']:
                    fiche['2205'] = '3'
                errors += [f"- {label}: {error}" for error in zone_errors + self._get_belcotax_schema_errors(schema, fiche)]
                fiches.append(fiche)
        return [contact, debtor, *persons.values(), *fiches], errors

    def _render_jsonl(self):
        self.ensure_one()
        documents, errors = self._get_belcotax_documents()
        if errors:
            error_header = self.env._("Cannot generate the JSON Lines file. Please fix the following errors:\n\n")
            return False, error_header + "\n".join(errors)
        content = ''.join(f'{self._dump_belcotax_document(document)}\n' for document in documents)
        return BinaryBytes(content.encode()), False

    def _get_undeclared_payslips(self, employees):
        """Payslips of the year that no filed declaration covers yet. Returns {source declaration: payslips}."""
        self.ensure_one()
        year = int(self.year)
        Payslip = self.env['hr.payslip']
        payslips = Payslip.search(Domain([
            ('state', 'in', ['validated', 'paid']),
            ('employee_id', 'in', employees.ids),
            ('version_id.no_withholding_taxes', '=', False),
        ]) & Payslip._l10n_be_get_fiscal_period_domain(date(year, 1, 1), date(year, 12, 31)))
        filed_274 = self.env['l10n_be.274_xx'].search([
            ('year', '=', year),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['ready', 'done']),
        ])
        undeclared_274 = payslips - filed_274.payslip_ids
        # Only the payslips with intellectual property withholding taxes have to be declared in the 273S.
        ip_codes = self.env['l10n.be.281.mapping']._get_codes_for_tag('273S', '273s_withholding_tax', year)
        undeclared_273 = Payslip
        if ip_codes:
            line_values = payslips._get_line_values(
                ip_codes, extra_domain=Payslip._l10n_be_get_fiscal_line_domain(date(year, 1, 1), date(year, 12, 31)))
            filed_273_lines = self._get_filed_273_sheets().line_ids.filtered(lambda line: line.report_type == 'ip')
            undeclared_273 = payslips.filtered(
                lambda p: any(line_values[code][p.id]['total'] for code in ip_codes)
            ) - filed_273_lines.payslip_id
        return {
            **dict.fromkeys(self._get_withholding_sources().values(), undeclared_274),
            '273S': undeclared_273,
        }

    def _get_withholding_check_values(self):
        """Lines comparing, per 281 form and employee, the withholding taxes of the forms with the ones
        declared during the year, and hinting at the origin of each difference."""
        self.ensure_one()
        year = int(self.year)
        currency = self.company_id.currency_id
        groups = defaultdict(list)
        for report_key, source in self._get_withholding_sources().items():
            config = REPORT_CONFIG[report_key]
            form = self[config['relation_field']][:1]
            if not form:
                continue
            if not self[config['include_field']]:
                groups[report_key, self.env['hr.employee']].append({
                    'origin': '281',
                    'source': report_key,
                    'note': self.env._("This form is not included in the declaration."),
                })
                continue
            try:
                amounts, errors = form._get_withholding_amounts()
            except UserError as e:
                groups[report_key, self.env['hr.employee']].append({
                    'origin': '281',
                    'source': report_key,
                    'note': e.args[0],
                })
                continue
            for employee in form.line_ids.employee_id:
                groups[report_key, employee].append({
                    'origin': '281',
                    'source': report_key,
                    'amount_281': amounts.get(employee, 0.0),
                    'note': errors.get(employee, False),
                })

        for line in self._get_declared_withholding_lines():
            document = line['document']
            groups[line['report'], line['employee']].append({
                'origin': 'declared',
                'source': line['source'],
                'document': f'{document._name},{document.id}',
                'date': document.date_start if document._name == 'l10n_be.274_xx' else document.period,
                'declared_amount': line['amount'],
                'note': document.is_correction_needed and self.env._(
                    "Payslips changed since this declaration was filed."),
            })

        inconsistent_groups = {
            key: vals_list for key, vals_list in groups.items()
            if key[1] and currency.compare_amounts(
                sum(vals.get('amount_281', 0.0) for vals in vals_list),
                sum(vals.get('declared_amount', 0.0) for vals in vals_list),
            )
        }
        undeclared_payslips = self._get_undeclared_payslips(
            self.env['hr.employee'].browse({employee.id for dummy, employee in inconsistent_groups}))
        for (report_key, employee), vals_list in inconsistent_groups.items():
            annual_vals = [vals for vals in vals_list if vals['origin'] == '281']
            declared_vals = [vals for vals in vals_list if vals['origin'] == 'declared']
            if not annual_vals:
                for vals in declared_vals:
                    vals['note'] = vals['note'] or self.env._("This employee is not on the %s form.", report_key)
            elif not declared_vals:
                for vals in annual_vals:
                    vals['note'] = vals['note'] or self.env._("Nothing was declared for this employee during the year.")
            source = self._get_withholding_sources()[report_key]
            if payslips := undeclared_payslips[source].filtered(lambda p: p.employee_id == employee):
                vals_list.append({
                    'origin': 'undeclared',
                    'source': source,
                    'note': self.env._(
                        "Payslips not covered by any filed %(declaration)s declaration: %(payslips)s",
                        declaration=source, payslips=', '.join(payslips.mapped('name'))),
                })

        # Form level issues (no employee) only matter when they leave the form inconsistent.
        inconsistent_reports = {report_key for report_key, dummy in inconsistent_groups}
        return [{
            'declaration_id': self.id,
            'report': report_key,
            'employee_id': employee.id,
            'date': date(year, 12, 31),
            'is_inconsistent': (report_key, employee) in inconsistent_groups or (
                not employee and report_key in inconsistent_reports),
            **vals,
        } for (report_key, employee), vals_list in groups.items() for vals in vals_list]

    def action_open_withholding_check(self):
        self.ensure_one()
        check_lines = self.env['l10n_be.281_xx.withholding.check']
        check_lines.search([('declaration_id', '=', self.id)]).unlink()
        check_lines = check_lines.create(self._get_withholding_check_values())
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Withholding Taxes Check %s", self.year),
            'res_model': 'l10n_be.281_xx.withholding.check',
            'view_mode': 'list,pivot',
            'domain': [('id', 'in', check_lines.ids)],
            'context': {
                'search_default_group_report': 1,
                'search_default_group_employee': 1,
                'search_default_inconsistent': int(any(check_lines.mapped('is_inconsistent'))),
            },
        }
