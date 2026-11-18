from datetime import date

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import BinaryBytes, mute_logger
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# Reference values from the submitted declaration (Print.pdf) and the rs.ge template temp_15_2.xml.
TBILISI_VAKE = 'gec_property_tax_report.land_territory_78703'   # rate 1.5 for type 33
KUTAISI_ZONE1 = 'gec_property_tax_report.land_territory_78671'  # rate 1.25
NON_AGRI = 'gec_property_tax_report.land_type_33'
ARABLE = 'gec_property_tax_report.land_type_55'
POTI = 'gec_property_tax_report.territory_1195'
CARS = 'gec_property_tax_report.property_type_2'                # 1.1, movable
BUILDINGS = 'gec_property_tax_report.property_type_19'          # 4, immovable
EXEMPTION_206 = 'gec_property_tax_report.exemption_1'


class Form15Common(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Every asset variant needs a depreciation model.
        cls.depreciation_model = cls.env['account.depreciation.model'].create({
            'method': 'linear',
            'method_number': 5,
            'method_period': '12',
            'company_id': cls.company.id,
        })
        # Land keeps this one: an asset a plot is attached to is not depreciated.
        cls.no_depreciation_model = cls.env['account.depreciation.model'].create({
            'name': 'Land',
            'method': 'no_depreciation',
            'company_id': cls.company.id,
        })
        cls.declaration = cls.env['rs.form15.declaration'].create({
            'company_id': cls.company.id,
            'date_from': '2025-01-01',
        })

    def _running_asset(self, vals):
        """`state` is ignored on create; it lives on the main variant."""
        asset = self.env['account.asset'].create({'model_id': self.depreciation_model.id, **vals})
        asset.main_variant_id.state = 'open'
        return asset

    def _plot(self, territory, land_type, area, **extra):
        return self.env['rs.form15.land.plot'].create({
            'name': 'Plot %s' % area,
            'company_id': self.company.id,
            'land_territory_id': self.env.ref(territory).id,
            'land_type_id': self.env.ref(land_type).id,
            'area': area,
            **extra,
        })


@tagged('post_install', '-at_install')
class TestForm15Classifiers(Form15Common):

    def test_data_loaded(self):
        """The rs.ge workbooks must arrive whole: a short matrix silently zeroes rates."""
        self.assertEqual(self.env['rs.form15.property.type'].search_count([]), 20)
        self.assertEqual(self.env['rs.form15.territory'].search_count([]), 78)
        self.assertEqual(self.env['rs.form15.exemption.basis'].search_count([]), 6)
        self.assertEqual(self.env['rs.form15.land.territory'].with_context(active_test=False).search_count([]), 263)
        self.assertEqual(self.env['rs.form15.land.type'].with_context(active_test=False).search_count([]), 11)
        self.assertEqual(self.env['rs.form15.land.rate'].search_count([]), 2893)

    def test_non_agricultural_is_a_coefficient(self):
        """Only land type 33 multiplies the statutory base rate; the rest are absolute."""
        non_agri = self.env.ref(NON_AGRI)
        self.assertTrue(non_agri.uses_base_rate)
        self.assertEqual(non_agri.unit, 'sqm')
        self.assertAlmostEqual(non_agri.base_rate, 0.24)
        self.assertAlmostEqual(non_agri._unit_rate(1.5), 0.36)
        arable = self.env.ref(ARABLE)
        self.assertFalse(arable.uses_base_rate)
        self.assertEqual(arable.unit, 'ha')
        self.assertAlmostEqual(arable._unit_rate(87), 87)

    def test_exemption_validity_windows(self):
        """The validity notes rs.ge ships as free text must become real date bounds."""
        self.assertTrue(self.env.ref(EXEMPTION_206)._is_valid(2025))
        expired = self.env.ref('gec_property_tax_report.exemption_13')
        self.assertTrue(expired._is_valid(2019))
        self.assertFalse(expired._is_valid(2025))

    def test_revaluation_bands(self):
        bands = self.env['rs.form15.revaluation.coefficient']
        self.assertAlmostEqual(bands._band_for(1998).coefficient, 3)
        self.assertAlmostEqual(bands._band_for(2002).coefficient, 2)
        self.assertAlmostEqual(bands._band_for(2004).coefficient, 1.5)
        self.assertAlmostEqual(bands._band_for(2025).coefficient, 1)
        self.assertEqual(bands._band_for(2025).code, '-')
        # An unknown acquisition year takes the highest band, as the rs.ge table states.
        self.assertAlmostEqual(bands._band_for(0).coefficient, 3)


@tagged('post_install', '-at_install')
class TestForm15Land(Form15Common):

    def test_print_pdf_rows(self):
        """Reproduces the five part IV rows of the submitted declaration."""
        self._plot(TBILISI_VAKE, NON_AGRI, 200)
        self._plot(KUTAISI_ZONE1, NON_AGRI, 200)
        self.declaration.action_generate_part4()
        taxes = sorted(self.declaration.part4_line_ids.mapped('tax_amount'))
        self.assertEqual(taxes, [60.0, 72.0])
        rates = sorted(self.declaration.part4_line_ids.mapped('rate'))
        self.assertEqual(rates, [1.25, 1.5])

    def test_rs_template_row(self):
        """rs.ge's own sample: 1000 m² in Tbilisi at coefficient 1.5 is 360 GEL."""
        self._plot(TBILISI_VAKE, NON_AGRI, 1000)
        self.declaration.action_generate_part4()
        self.assertAlmostEqual(self.declaration.part4_line_ids.tax_amount, 360.0)

    def test_exemption_reduces_the_taxed_area(self):
        self._plot(TBILISI_VAKE, NON_AGRI, 200,
                   exemption_basis_id=self.env.ref(EXEMPTION_206).id, taxable_area=150)
        self.declaration.action_generate_part4()
        line = self.declaration.part4_line_ids
        self.assertAlmostEqual(line.tax_amount, 54.0)  # 150 x 0.24 x 1.5
        self.assertAlmostEqual(line.taxable_area, 150)

    def test_taxable_area_without_a_basis_is_refused(self):
        with self.assertRaises(ValidationError):
            self._plot(TBILISI_VAKE, NON_AGRI, 200, taxable_area=150)

    def test_only_plots_owned_on_the_reference_date(self):
        """Owned on 1 April itself counts: bought that day is in, sold that day is out."""
        self.declaration.land_reference_date = '2025-04-01'
        kept = (
            self._plot(TBILISI_VAKE, NON_AGRI, 100),
            self._plot(TBILISI_VAKE, NON_AGRI, 200, date_acquired='2025-04-01'),
            self._plot(TBILISI_VAKE, NON_AGRI, 300, date_sold='2025-04-02'),
        )
        self._plot(TBILISI_VAKE, NON_AGRI, 400, date_acquired='2025-06-10')
        self._plot(TBILISI_VAKE, NON_AGRI, 500, date_sold='2025-04-01')
        self.declaration.action_generate_part4()
        self.assertEqual(self.declaration.part4_line_ids.plot_id, self.env['rs.form15.land.plot'].concat(*kept))

    def test_archived_plot_sold_after_reference_date_is_declared(self):
        self.declaration.land_reference_date = '2025-04-01'
        plot = self._plot(TBILISI_VAKE, NON_AGRI, 100, date_sold='2025-06-10')
        plot.active = False
        self.declaration.action_generate_part4()
        self.assertEqual(self.declaration.part4_line_ids.plot_id, plot)

    def test_archived_plot_without_sale_date_is_left_out(self):
        """Archiving was the documented way to drop a plot before Sold On existed."""
        self.declaration.land_reference_date = '2025-04-01'
        self._plot(TBILISI_VAKE, NON_AGRI, 100).active = False
        self.declaration.action_generate_part4()
        self.assertFalse(self.declaration.part4_line_ids)

    def test_months_locked_after_export(self):
        """The exported file is what was filed: the rows behind it must not move."""
        self._plot(TBILISI_VAKE, NON_AGRI, 100)
        self.declaration.action_generate_part4()
        self.declaration.action_export()
        with self.assertRaises(UserError):
            self.declaration.months_of_existence = 6

    def test_readonly_user_can_download_explanation(self):
        auditor = self.env['res.users'].create({
            'name': 'Auditor', 'login': 'ptax_auditor', 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('account.group_account_readonly').id])],
        })
        self._plot(TBILISI_VAKE, NON_AGRI, 100)
        self.declaration.action_generate_part4()
        action = self.declaration.with_user(auditor).action_export_explanation()
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def _land_asset(self, name):
        return self._running_asset({'name': name, 'company_id': self.company.id,
                                    'model_id': self.no_depreciation_model.id,
                                    'original_value': 1000, 'acquisition_date': '2020-01-01'})

    def _draft_asset(self, model):
        return self.env['account.asset'].create({'name': 'Vake land', 'company_id': self.company.id,
                                                 'model_id': model.id, 'original_value': 1000,
                                                 'acquisition_date': '2020-01-01'})

    def test_attached_land_keeps_no_depreciation(self):
        land = self._draft_asset(self.no_depreciation_model)
        self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=land.id)
        with self.assertRaisesRegex(ValidationError, 'is attached to the land plot'):
            land.model_id = self.depreciation_model
        with self.assertRaisesRegex(ValidationError, 'is attached to the land plot'):
            land.main_variant_id.model_id = self.depreciation_model
        self.assertEqual(land.model_id, self.no_depreciation_model)

    def test_attaching_a_depreciating_asset_is_refused(self):
        office = self._draft_asset(self.depreciation_model)
        with self.assertRaisesRegex(ValidationError, 'is attached to the land plot'):
            self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=office.id)

    def test_detached_asset_may_depreciate(self):
        land = self._draft_asset(self.no_depreciation_model)
        plot = self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=land.id)
        plot.asset_id = False
        land.model_id = self.depreciation_model
        self.assertEqual(land.main_variant_id.model_id, self.depreciation_model)

    def test_relinking_a_plot_releases_the_previous_asset(self):
        office, land = self._land_asset('Office building'), self._land_asset('Vake land')
        plot = self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=office.id)
        plot.asset_id = land
        self.assertFalse(office.rs_form15_excluded, "the wrong pick goes back to part III")
        self.assertTrue(land.rs_form15_excluded)

    def test_an_asset_links_one_plot_only(self):
        land = self._land_asset('Vake land')
        self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=land.id)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._plot(TBILISI_VAKE, NON_AGRI, 200, asset_id=land.id)
            self.env.flush_all()

    def test_deleting_a_plot_releases_its_asset(self):
        office = self._land_asset('Office building')
        self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=office.id).unlink()
        self.assertFalse(office.rs_form15_excluded)

    def test_sold_before_acquired_is_refused(self):
        with self.assertRaises(ValidationError):
            self._plot(TBILISI_VAKE, NON_AGRI, 100, date_acquired='2025-05-01', date_sold='2025-02-01')

    def test_linked_asset_supplies_dates_and_leaves_part3(self):
        asset = self._running_asset({
            'name': 'Vake land',
            'company_id': self.company.id,
            'model_id': self.no_depreciation_model.id,
            'original_value': 50000,
            'acquisition_date': '2025-06-10',
        })
        plot = self._plot(TBILISI_VAKE, NON_AGRI, 100, asset_id=asset.id)
        self.assertTrue(asset.rs_form15_excluded, "land is taxed by area in part IV, not by value in part III")
        self.assertEqual(plot.date_acquired, date(2025, 6, 10))
        self.assertFalse(plot.date_sold)
        asset.main_variant_id.write({'state': 'close', 'disposal_date': '2026-02-01'})
        self.assertEqual(plot.date_sold, date(2026, 2, 1))
        plot.asset_id = False
        self.assertEqual(plot.date_acquired, date(2025, 6, 10), "unlinking keeps the dates")
        self.assertFalse(asset.rs_form15_excluded, "an unlinked asset goes back to part III")

    def test_rate_must_match_the_rs_table(self):
        """The portal derives the rate, so a row that disagrees would be silently
        overwritten on import. Refuse it here instead."""
        self._plot(TBILISI_VAKE, NON_AGRI, 200)
        self.declaration.action_generate_part4()
        with self.assertRaises(ValidationError):
            self.declaration.part4_line_ids.rate = 0.9

    def test_export_is_spreadsheetml(self):
        self._plot(TBILISI_VAKE, NON_AGRI, 1000)
        self.declaration.action_generate_part4()
        self.declaration.action_export()
        self.assertEqual(self.declaration.state, 'exported')
        self.assertEqual(self.declaration.export_filename_4, 'form15_part4_%s_%s.xml' % (
            self.company.vat or self.company.id, self.declaration.land_year))
        xml = self.declaration.export_file_4.content.decode()
        self.assertIn('urn:schemas-microsoft-com:office:spreadsheet', xml)
        self.assertIn('progid="Excel.Sheet"', xml)
        # ID, name, area, coefficient and tax, exactly as temp_15_2.xml carries them.
        for value in ('78703', '33', '1000', '1.5', '360'):
            self.assertIn('>%s<' % value, xml)

    def test_reset_to_draft_drops_the_exported_files(self):
        """An old file must not stay downloadable once the rows can change again."""
        self._plot(TBILISI_VAKE, NON_AGRI, 1000)
        self.declaration.action_generate_part4()
        self.declaration.action_export()
        self.assertTrue(self.declaration.export_file_4)
        self.declaration.action_draft()
        self.assertFalse(self.declaration.export_file_4)
        self.assertFalse(self.declaration.export_filename_4)

    def test_export_drops_the_file_of_an_emptied_part(self):
        self._plot(TBILISI_VAKE, NON_AGRI, 1000)
        self.declaration.action_generate_part4()
        self.declaration.write({'export_file_3': BinaryBytes(b'old'), 'export_filename_3': 'old.xml'})
        self.declaration.action_export()
        self.assertFalse(self.declaration.export_file_3)
        self.assertTrue(self.declaration.export_file_4)

    def test_export_refuses_an_empty_declaration(self):
        with self.assertRaises(UserError):
            self.declaration.action_export()


@tagged('post_install', '-at_install')
class TestForm15Property(Form15Common):
    """Part III arithmetic, driven through manual rows so no depreciation board is
    needed. The asset reader is covered separately by test_book_value."""

    def _line(self, **extra):
        self.declaration.write({'part3_line_ids': [Command.create({
            'property_type_id': self.env.ref(CARS).id,
            'territory_id': self.env.ref(POTI).id,
            'tax_rate': 1.0,
            **extra,
        })]})
        return self.declaration.part3_line_ids[-1]

    def test_print_pdf_rows(self):
        """The three part III rows of the submitted declaration, Poti at 1%."""
        for value, expected in ((5434.53, 54.35), (2958.34, 29.58), (24583.34, 245.83)):
            line = self._line(average_value=value)
            self.assertAlmostEqual(line.tax_amount, expected)
        self.assertAlmostEqual(self.declaration.part3_total, 329.76)

    def test_instruction_example_partial_year(self):
        """Order 996 art. 88: registered 22.02.2018, so 10 months; 1050 -> 875."""
        self.declaration.months_of_existence = 10
        line = self._line(average_value=105000)
        self.assertAlmostEqual(line.tax_amount, 1050.0)
        self.assertAlmostEqual(line.prorated_amount, 875.0)
        # Art. 205(3), (9): next year's advance is the full column 11, due 15 June.
        self.assertAlmostEqual(self.declaration.next_advance_amount, 1050.0)
        self.assertEqual(str(self.declaration.next_advance_date), '2026-06-15')

    def test_advance_is_subtracted(self):
        line = self._line(average_value=105000, advance_amount=1000)
        self.assertAlmostEqual(line.difference, 50.0)

    def test_revaluation_coefficient_multiplies(self):
        office = self._running_asset({'name': 'Office', 'company_id': self.company.id, 'original_value': 1,
                                      'acquisition_date': '1998-01-01', 'rs_form15_excluded': True})
        line = self._line(property_type_id=self.env.ref(BUILDINGS).id, asset_id=office.id,
                          acquisition_year_id=self.env['rs.form15.year']._for_year(1998).id, average_value=10000,
                          revaluation_coefficient_id=self.env.ref(
                              'gec_property_tax_report.revaluation_pre_2000').id)
        self.assertAlmostEqual(line.tax_amount, 300.0)  # 10000 x 3 x 1%

    def test_movable_property_refuses_columns_5_and_7(self):
        """The portal hides both columns for movable types, so they must go out empty."""
        with self.assertRaises(ValidationError):
            self._line(average_value=1000, acquisition_year_id=self.env['rs.form15.year']._for_year(2018).id)

    def test_rate_is_capped_at_one_percent(self):
        with self.assertRaises(ValidationError):
            self._line(average_value=1000, tax_rate=1.5)

    def test_untagged_assets_abort_generation(self):
        """Both columns are portal dropdowns, so a free-text fallback is impossible."""
        self._running_asset({
            'name': 'Untagged machine',
            'company_id': self.company.id,
            'original_value': 1000,
            'acquisition_date': '2024-01-01',
        })
        with self.assertRaises(UserError):
            self.declaration.action_generate_part3()

    def test_book_value_before_acquisition_is_zero(self):
        asset = self._running_asset({
            'name': 'Machine',
            'company_id': self.company.id,
            'original_value': 1000,
            'acquisition_date': '2025-06-01',
            'rs_form15_excluded': True,
        })
        self.assertAlmostEqual(asset._rs_form15_book_value(date(2025, 1, 1)), 0.0)
        self.assertAlmostEqual(asset._rs_form15_book_value(date(2025, 12, 31)), 1000.0)

    def test_exemption_capped_at_the_asset_value(self):
        """An amount typed in an earlier year must not cut the tax of other assets in the row."""
        asset = self._running_asset({
            'name': 'Laptop', 'company_id': self.company.id, 'original_value': 1000,
            'acquisition_date': '2024-01-01', 'rs_form15_excluded': True,
            'rs_form15_exemption_basis_id': self.env.ref(EXEMPTION_206).id,
            'rs_form15_exemption_amount': 5000,
        })
        self.assertAlmostEqual(asset._rs_form15_exemption(1000), 1000)

    def test_international_company_exemption(self):
        """Order 996 art. 88: 120 000 / 12 x 8 = 80 000."""
        asset = self._running_asset({
            'name': 'Office',
            'company_id': self.company.id,
            'original_value': 1,
            'acquisition_date': '2020-01-01',
            'rs_form15_excluded': True,
            'rs_form15_international_company_months': 8,
        })
        self.assertAlmostEqual(asset._rs_form15_exemption(120000), 80000.0)

    def test_explain_matches_the_stored_values(self):
        line = self._line(average_value=105000)
        trace = line._explain()
        total = [step for step in trace['steps'] if step.get('total')]
        self.assertTrue(trace['title'])
        self.assertTrue(trace['formula'])
        self.assertEqual(len(total), 1)


@tagged('post_install', '-at_install')
class TestForm15Declaration(Form15Common):

    def test_one_declaration_per_company_and_year(self):
        """Two records for one year would let two different files exist for one filing."""
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['rs.form15.declaration'].create({
                    'company_id': self.company.id, 'date_from': '2025-01-01'})

    def test_period_must_start_on_1_january(self):
        with self.assertRaises(ValidationError):
            self.declaration.date_from = '2025-06-01'

    def test_period_derives_the_year(self):
        self.assertEqual(self.declaration.tax_year, 2025)
        self.assertEqual(str(self.declaration.date_to), '2025-12-31')
        # Part IV follows its own reference date, not the period.
        self.assertEqual(self.declaration.land_year,
                         self.declaration.land_reference_date.year)

    def test_land_is_reported_for_the_filing_year(self):
        """Tax Code art. 205(2): property for the past year, land for the current one."""
        self.declaration._onchange_date_from()
        self.assertEqual(str(self.declaration.land_reference_date), '2026-04-01')

    def test_months_of_existence_bounds(self):
        with self.assertRaises(ValidationError):
            self.declaration.months_of_existence = 12

    def test_building_rate_falls_back_to_the_cap(self):
        """rs.ge publishes no part III rate table, so an unset unit takes the 1% cap
        and the row says so."""
        rate, from_table = self.env['rs.form15.building.rate']._rate_for(
            self.env.ref(POTI), 2025)
        self.assertAlmostEqual(rate, 1.0)
        self.assertFalse(from_table)

    def test_seed_year_covers_every_unit(self):
        self.env['rs.form15.building.rate']._seed_year(2025)
        self.assertEqual(
            self.env['rs.form15.building.rate'].search_count([('tax_year', '=', 2025)]), 78)

    def test_building_rate_cannot_exceed_one_percent(self):
        with self.assertRaises(ValidationError):
            self.env['rs.form15.building.rate'].create({
                'territory_id': self.env.ref(POTI).id, 'tax_year': 2025, 'rate': 1.5})
