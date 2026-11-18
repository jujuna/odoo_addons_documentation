import csv

from psycopg2 import IntegrityError

from odoo import Command, api, models
from odoo.addons.account.models.chart_template import template
from odoo.exceptions import UserError
from odoo.tools import file_open, mute_logger

GE_TAX_TEXTS_KEY = 'gec_localization.tax_texts_20261023'
GE_RC_TEXTS_KEY = 'gec_localization.tax_texts_rc_20261104'
GE_TAX_CATEGORIES_KEY = 'gec_localization.tax_categories_20261028'
GE_REMOVED_TAXES = ('ge_tax_p_wht_res_rent_5_cp',)
GE_WRONG_REPLACEMENTS = {
    'ge_vat_sale_18_sp_sale': 'ge_vat_sale_18',
    'ge_vat_sale_18_adv': 'ge_vat_sale_18',
    'ge_vat_sale_18_other': 'ge_vat_sale_18',
    'ge_vat_sale_exempt_financial': 'ge_vat_sale_18',
    'ge_vat_sale_exempt_land': 'ge_vat_sale_18',
    'ge_vat_sale_exempt_other': 'ge_vat_sale_18',
    'ge_rcvat_18_ser': 'ge_vat_purchase_18',
    'ge_rcvat_18_goods_customs': 'ge_vat_purchase_18',
    'ge_rcvat_18_goods_fiz': 'ge_vat_purchase_18',
}
GE_VAT_POSITION = 'ge_fiscal_position_vat'
GE_DOMESTIC_POSITIONS = ('ge_fiscal_position_nonvat', 'ge_fiscal_position_domestic')
GE_DOMESTIC_SALE_TAXES = ('ge_vat_sale_18', 'ge_vat_sale_18_sp_sale', 'ge_vat_sale_18_adv', 'ge_vat_sale_18_building', 'ge_vat_sale_18_repairs',
    'ge_vat_sale_18_barter', 'ge_vat_sale_18_other', 'ge_vat_sale_exempt_financial', 'ge_vat_sale_exempt_land', 'ge_vat_sale_exempt_other')
GE_IMPORT_VAT_TAXES = ('ge_import_duty_18', 'ge_import_duty_12', 'ge_import_duty_5')


def _read_ge_core_tax_texts():
    """{xmlid: {field: value}} of our l10n_ge tax names, descriptions, invoice labels (en, ka) and Tax Category Code.
    Empty cells are dropped, as core does, so the l10n_ge value stays."""
    with file_open('gec_localization/data/template/ge_core_tax_texts.csv', 'r') as csv_file:
        return {
            row['id']: {
                key: value.strip() for key, value in row.items()
                if key and key != 'id' and value and value.strip()
            }
            for row in csv.DictReader(csv_file) if row['id']
        }


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('ge', 'account.account')
    def _get_ge_gec_account_account(self):
        """Our accounts on top of l10n_ge's chart, plus overrides of four of its accounts.
        Pension 332010: Payable + reconcilable; 310310: Payable; 331310: non-reconcilable.
        WHT Settled 331211 (core Expense): non-trade Payable, so Pay settles it. Payroll income tax posts to 331320."""
        return self._parse_csv('ge', 'account.account', module='gec_localization')

    @template('ge', 'account.tax.group')
    def _get_ge_gec_account_tax_group(self):
        return self._parse_csv('ge', 'account.tax.group', module='gec_localization')

    @template('ge', 'account.tax')
    def _get_ge_gec_account_tax(self):
        """Taxes l10n_ge does not ship (withholding, turnover, CIT, out of scope ...).
        The reverse-charge one carries l10n_ge's report tags 21(B)/21(T) so Odoo's VAT report sees it."""
        tax_data = self._parse_csv('ge', 'account.tax', module='gec_localization')
        self._deref_account_tags('ge', tax_data)
        return tax_data

    @template(model='account.tax')
    def _get_account_tax(self, template_code):
        """Correct l10n_ge's tax data on every 'ge' chart load: drop nine wrong "Replaces" links,
        keep domestic sale taxes for buyers without a Tax ID, make the three import-VAT-only taxes price-included,
        set names, labels and Tax Category Codes from ge_core_tax_texts.csv. Ids via .get(): indexing creates an empty row."""
        tax_data = super()._get_account_tax(template_code)
        if template_code != 'ge':
            return tax_data
        for xmlid, source in GE_WRONG_REPLACEMENTS.items():
            values = tax_data.get(xmlid)
            if values and values.get('original_tax_ids'):
                rest = [x for x in values['original_tax_ids'].split(',') if x != source]
                if rest:
                    values['original_tax_ids'] = ','.join(rest)
                else:
                    values.pop('original_tax_ids', None)
        for xmlid in GE_DOMESTIC_SALE_TAXES:
            values = tax_data.get(xmlid)
            positions = [x for x in (values or {}).get('fiscal_position_ids', '').split(',') if x]
            if GE_VAT_POSITION in positions:
                positions += [x for x in GE_DOMESTIC_POSITIONS if x not in positions]
                values['fiscal_position_ids'] = ','.join(positions)
        for xmlid in GE_IMPORT_VAT_TAXES:
            if xmlid in tax_data:
                tax_data[xmlid]['price_include_override'] = 'tax_included'
        for xmlid, values in _read_ge_core_tax_texts().items():
            if xmlid in tax_data:
                tax_data[xmlid].update(values)
        return tax_data

    @api.model
    def _ge_fix_core_vat_taxes(self, companies=None):
        """Apply the _get_account_tax corrections to existing records (install and every 'ge' chart load).
        Only the wrong "Replaces" link is removed and an empty price-included value filled, so edits survive;
        archived records included."""
        if companies is None:
            companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        for company in companies:
            tpl = self.with_company(company).with_context(active_test=False)
            for xmlid, source_xmlid in GE_WRONG_REPLACEMENTS.items():
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                source = tpl.ref(source_xmlid, raise_if_not_found=False)
                if tax and source and source in tax.original_tax_ids:
                    tax.original_tax_ids = [Command.unlink(source.id)]
            vat_position = tpl.ref(GE_VAT_POSITION, raise_if_not_found=False)
            domestic = [position for xmlid in GE_DOMESTIC_POSITIONS if (position := tpl.ref(xmlid, raise_if_not_found=False))]
            for xmlid in GE_DOMESTIC_SALE_TAXES:
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                if tax and vat_position and vat_position in tax.fiscal_position_ids:
                    tax.fiscal_position_ids = [Command.link(position.id) for position in domestic]
            for xmlid in GE_IMPORT_VAT_TAXES:
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                if tax and not tax.price_include_override:
                    tax.price_include_override = 'tax_included'

    def _post_load_data(self, template_code, company, template_data):
        super()._post_load_data(template_code, company, template_data)
        if template_code == 'ge' and not company.parent_id:
            self._ge_gec_apply_maintenance(company)
            self._ge_fix_core_vat_taxes(company)

    @api.model
    def _ge_gec_apply_maintenance(self, companies=None):
        """Create our template records missing in a 'ge' company, matching hand-made records first as a chart reload does.
        Give each company its own WHT certificate sequence. Existing records are rewritten only by _ge_apply_tax_texts;
        new Bank and Cash accounts get no journal; Georgian names never overwrite a set name. @api.model: for the data <function> tag."""
        if companies is None:
            companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        shared_seq = self.env.ref('gec_localization.seq_ge_wht', raise_if_not_found=False)
        for company in companies:
            tpl = self.with_company(company)
            data = tpl._get_chart_template_data('ge', module='gec_localization')
            data.pop('template_data', None)
            missing = {
                model: {xid: vals for xid, vals in records.items() if not tpl.ref(xid, raise_if_not_found=False)}
                for model, records in data.items()
            }
            missing = {model: records for model, records in missing.items() if records}
            if missing:
                tpl._pre_reload_data(company, {}, missing)
                tpl._pre_load_data('ge', company, {}, missing)
                tpl.with_context(skip_auto_account_journal_creation=True)._load_data(missing)
            if shared_seq:
                company_seq = self._ge_wht_company_sequence(shared_seq, company)
                self.env['account.tax'].search([
                    ('company_id', '=', company.id),
                    ('is_withholding_tax', '=', True),
                    ('withholding_sequence_id', 'in', (False, shared_seq.id)),
                ]).write({'withholding_sequence_id': company_seq.id})
        if companies:
            self._ge_apply_tax_texts()
            self._ge_apply_tax_texts(GE_RC_TEXTS_KEY, ('ge_tax_p_rc_18_nonvatreg',))
            self._ge_apply_tax_categories()
            self._load_translations(companies=companies)

    @api.model
    def _ge_apply_tax_texts(self, key=GE_TAX_TEXTS_KEY, xmlids=None):
        """Once per database and key: remove retired taxes (archive if used); set template name, description and invoice
        label (en, ka) on 'ge' company taxes, only `xmlids` when given; no Georgian text keeps the stored one.
        One dict write per field: per-language Html writes mismap terms."""
        params = self.env['ir.config_parameter'].sudo()
        if params.get_bool(key):
            return
        companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        template_values = self.with_context(ignore_missing_tags=True)._get_chart_template_model_data('ge', 'account.tax')
        text_xmlids = sorted({*_read_ge_core_tax_texts(),
            *self._parse_csv('ge', 'account.tax', module='gec_localization')} & template_values.keys() & set(xmlids or template_values))
        has_ka = bool(self.env['res.lang']._lang_get('ka_GE'))
        for company in companies:
            # sudo: the pass covers every Georgian company, also those the current user cannot open
            tpl = self.sudo().with_company(company).with_context(active_test=False)
            for xmlid in GE_REMOVED_TAXES:
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                if tax:
                    try:
                        with self.env.cr.savepoint(), mute_logger('odoo.sql_db'):
                            tax.unlink()
                    except (UserError, IntegrityError):
                        tax.active = False
            for xmlid in text_xmlids:
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                if not tax:
                    continue
                values = template_values[xmlid]
                vals = {}
                for fname in ('name', 'description', 'invoice_label'):
                    en = values.get(fname)
                    if not en:
                        continue
                    if not has_ka:
                        vals[fname] = en
                        continue
                    stored = tax._get_stored_translations(fname)
                    ka = values.get(f'{fname}@ka') or (dict.get(stored, 'ka_GE') if stored is not None else None)
                    vals[fname] = {'en_US': en, 'ka_GE': ka} if ka else en
                if vals:
                    tax.with_context(lang='en_US', active_test=True).write(vals)
        params.set_bool(key, True)

    @api.model
    def _ge_apply_tax_categories(self):
        """Fill empty Tax Category Codes of existing Georgian taxes from the template CSVs, once per database."""
        params = self.env['ir.config_parameter'].sudo()
        if params.get_bool(GE_TAX_CATEGORIES_KEY):
            return
        template_taxes = {**_read_ge_core_tax_texts(), **self._parse_csv('ge', 'account.tax', module='gec_localization')}
        codes = {xmlid: values['ubl_cii_tax_category_code'] for xmlid, values in template_taxes.items() if values.get('ubl_cii_tax_category_code')}
        companies = self.env['res.company'].search([('chart_template', '=', 'ge'), ('parent_id', '=', False)])
        for company in companies:
            tpl = self.sudo().with_company(company).with_context(active_test=False)
            for xmlid, code in codes.items():
                tax = tpl.ref(xmlid, raise_if_not_found=False)
                if tax and not tax.ubl_cii_tax_category_code:
                    tax.ubl_cii_tax_category_code = code
        params.set_bool(GE_TAX_CATEGORIES_KEY, True)

    def _ge_wht_company_sequence(self, shared, company):
        """One certificate counter per legal entity, starting where the shared counter stands."""
        Sequence = self.env['ir.sequence']
        sequence = Sequence.search([('code', '=', shared.code), ('company_id', '=', company.id)], limit=1)
        return sequence or Sequence.create({
            'name': f"{shared.name} - {company.name}",
            'code': shared.code,
            'prefix': shared.prefix,
            'padding': shared.padding,
            'company_id': company.id,
            'number_next': shared.number_next_actual,
        })
