from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account_asset.tests.common import TestAccountAssetCommon

from .test_form15 import BUILDINGS, CARS, POTI, Form15Common

PIPELINES = 'gec_property_tax_report.property_type_14'     # 1.13, named, immovable
UNINSTALLED = 'gec_property_tax_report.property_type_17'   # 2, named, movable
CONSTRUCTION = 'gec_property_tax_report.property_type_18'  # 3, named, immovable
COMPUTERS = 'gec_property_tax_report.property_type_9'      # 1.8, unnamed, movable
FROM_2005 = 'gec_property_tax_report.revaluation_2005_on'
LEASED_MOVABLE = 'gec_property_tax_report.property_type_21'  # 5.1, named, movable, leasing


@tagged('post_install', '-at_install')
class TestForm15NamedRows(Form15Common):
    """Part III rows: named types (1.13, 2, 3, 4, 5.1, 5.2) get one row per object (asset or group) carrying
    its name in column 2; the rest aggregate per type and territorial unit."""

    def _asset(self, name, type_ref, value, acquired='2018-03-01', **extra):
        return self._running_asset({
            'name': name,
            'company_id': self.company.id,
            'original_value': value,
            'acquisition_date': acquired,
            'rs_form15_property_type_id': self.env.ref(type_ref).id,
            'rs_form15_territory_id': self.env.ref(POTI).id,
            **extra,
        })

    def _rows(self, declaration=None):
        declaration = declaration or self.declaration
        declaration.action_generate_part3()
        return declaration.part3_line_ids.filtered(lambda line: line.source == 'asset')

    def _previous_year(self, *rows):
        """Last year's filed building rows: (link vals, average value)."""
        previous = self.env['rs.form15.declaration'].create({
            'company_id': self.company.id, 'date_from': '2024-01-01'})
        previous.write({'part3_line_ids': [
            Command.create({'property_type_id': self.env.ref(BUILDINGS).id,
                            'territory_id': self.env.ref(POTI).id, 'tax_rate': 1.0,
                            'average_value': value,
                            'acquisition_year_id': self.env['rs.form15.year']._for_year(2018).id,
                            'revaluation_coefficient_id': self.env.ref(FROM_2005).id,
                            **link})
            for link, value in rows]})
        return previous

    def test_named_flags_match_the_portal(self):
        named = self.env['rs.form15.property.type'].search([('has_name', '=', True)])
        self.assertEqual(sorted(named.mapped('display_code')), ['1.13', '2', '3', '4', '5.1', '5.2'])

    def test_each_building_gets_its_own_row_linked_to_its_asset(self):
        office = self._asset('Office building', BUILDINGS, 100000)
        warehouse = self._asset('Warehouse', BUILDINGS, 50000)
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        by_asset = {row.asset_id: row for row in rows}
        self.assertEqual(by_asset[office].name, 'Office building')
        self.assertEqual(by_asset[office].asset_ids, office)
        self.assertEqual(by_asset[warehouse].name, 'Warehouse')
        self.assertAlmostEqual(by_asset[office].average_value, 100000)
        self.assertEqual(by_asset[office].acquisition_year_id.code, '2018')
        self.assertFalse(rows.asset_group_id)

    def test_an_asset_group_is_declared_as_one_object(self):
        """Construction in progress booked as one asset per bill line is one building."""
        site = self.env['account.asset.group'].create({'name': 'Batumi tower', 'company_id': self.company.id})
        bills = (self._asset('Concrete', CONSTRUCTION, 30000, acquired='2021-04-01', asset_group_id=site.id)
                 | self._asset('Steel', CONSTRUCTION, 20000, acquired='2019-09-01', asset_group_id=site.id)
                 | self._asset('Glass', CONSTRUCTION, 10000, acquired='2023-02-01', asset_group_id=site.id))
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertEqual(row.asset_group_id, site)
        self.assertFalse(row.asset_id)
        self.assertEqual(row.name, 'Batumi tower')
        self.assertEqual(row.asset_ids, bills)
        self.assertAlmostEqual(row.average_value, 60000)
        self.assertEqual(row.acquisition_year_id.code, '2019')  # the earliest asset

    def test_unnamed_types_still_aggregate(self):
        car_a = self._asset('Car A', CARS, 20000)
        car_b = self._asset('Car B', CARS, 30000)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.name)
        self.assertFalse(rows.asset_id)
        self.assertEqual(rows.asset_ids, car_a | car_b)
        self.assertAlmostEqual(rows.average_value, 50000)
        self.assertFalse(rows.acquisition_year_id)
        self.assertFalse(rows.revaluation_coefficient_id)

    def test_export_column_2_carries_the_name_only_for_named_types(self):
        self._asset('Main gas pipeline', PIPELINES, 80000)
        self._asset('Laptop', COMPUTERS, 3000)
        rows = self._rows()
        pipeline = rows.filtered('has_name')
        laptop = rows - pipeline
        self.assertEqual(pipeline._export_values()[:2], ['14', 'Main gas pipeline'])
        self.assertEqual(laptop._export_values()[:2], ['9', laptop.property_type_id.name])
        self.declaration.action_export()
        self.assertIn('Main gas pipeline', self.declaration.export_file_3.content.decode())

    def test_the_name_is_a_snapshot(self):
        """A filed row keeps the name it was filed with when the asset is renamed."""
        office = self._asset('Office building', BUILDINGS, 100000)
        row = self._rows()
        office.name = 'Head office'
        self.assertEqual(row.name, 'Office building')

    def test_pipeline_before_2000_takes_the_pre_2000_option_and_coefficient(self):
        self._asset('Old pipeline', PIPELINES, 10000, acquired='1998-05-01')
        row = self._rows()
        self.assertEqual(row.acquisition_year_id.code, '1999')
        self.assertEqual(row.revaluation_coefficient_id,
                         self.env.ref('gec_property_tax_report.revaluation_pre_2000'))
        self.assertAlmostEqual(row.tax_amount, 300.0)  # 10000 x 3 x 1%

    def test_uninstalled_equipment_is_named_but_movable(self):
        self._asset('Turbine in crates', UNINSTALLED, 40000)
        row = self._rows()
        self.assertEqual(row.name, 'Turbine in crates')
        self.assertFalse(row.acquisition_year_id)
        self.assertFalse(row.revaluation_coefficient_id)

    def test_advance_follows_each_asset(self):
        """Column 12 is last year's column 11 of the same object."""
        office = self._asset('Office building', BUILDINGS, 100000)
        warehouse = self._asset('Warehouse', BUILDINGS, 50000)
        self._previous_year(({'asset_id': office.id}, 100000), ({'asset_id': warehouse.id}, 50000))
        by_asset = {row.asset_id: row for row in self._rows()}
        self.assertAlmostEqual(by_asset[office].advance_amount, 1000.0)
        self.assertAlmostEqual(by_asset[warehouse].advance_amount, 500.0)

    def test_two_objects_with_the_same_name_keep_their_own_advance(self):
        """Two warehouses both called 'Warehouse' paid 500 and 300 last year."""
        north = self._asset('Warehouse', BUILDINGS, 50000)
        south = self._asset('Warehouse', BUILDINGS, 30000)
        self._previous_year(({'asset_id': north.id}, 50000), ({'asset_id': south.id}, 30000))
        by_asset = {row.asset_id: row for row in self._rows()}
        self.assertAlmostEqual(by_asset[north].advance_amount, 500.0)
        self.assertAlmostEqual(by_asset[south].advance_amount, 300.0)

    def test_a_named_row_must_say_which_object(self):
        with self.assertRaises(ValidationError):
            self.declaration.write({'part3_line_ids': [Command.create({
                'property_type_id': self.env.ref(UNINSTALLED).id,
                'territory_id': self.env.ref(POTI).id,
                'tax_rate': 1.0, 'average_value': 1000})]})

    def test_an_unnamed_row_refuses_an_asset(self):
        laptop = self._asset('Laptop', COMPUTERS, 3000)
        with self.assertRaises(ValidationError):
            self.declaration.write({'part3_line_ids': [Command.create({
                'property_type_id': self.env.ref(COMPUTERS).id, 'asset_id': laptop.id,
                'territory_id': self.env.ref(POTI).id,
                'tax_rate': 1.0, 'average_value': 1000})]})

    def test_an_object_is_declared_once(self):
        turbine = self._asset('Turbine in crates', UNINSTALLED, 40000)
        self._rows()
        with self.assertRaises(ValidationError):
            self.declaration.write({'part3_line_ids': [Command.create({
                'property_type_id': self.env.ref(UNINSTALLED).id, 'asset_id': turbine.id,
                'territory_id': self.env.ref(POTI).id,
                'tax_rate': 1.0, 'average_value': 1000})]})

    def test_depreciation_model_proposes_the_type(self):
        self.depreciation_model.rs_form15_property_type_id = self.env.ref(PIPELINES)
        proposed = self._running_asset({'name': 'Pipeline', 'company_id': self.company.id,
                                        'original_value': 1000, 'acquisition_date': '2020-01-01'})
        self.assertEqual(proposed.rs_form15_property_type_id, self.env.ref(PIPELINES))
        chosen = self._running_asset({'name': 'Car', 'company_id': self.company.id,
                                      'original_value': 1000, 'acquisition_date': '2020-01-01',
                                      'rs_form15_property_type_id': self.env.ref(CARS).id})
        self.assertEqual(chosen.rs_form15_property_type_id, self.env.ref(CARS))

    # ---- value at lease-out (Order 996 art. 88 d.a / d.b) ----------------------------

    def _leased(self, value=1000, base=50000, **extra):
        return self._asset('Leased excavator', LEASED_MOVABLE, value, rs_form15_leased_out=True,
                           rs_form15_leased_out_base_value=base, **extra)

    def _dispose(self, asset, on):
        asset.main_variant_id.write({'state': 'close', 'disposal_date': on})

    def test_lease_out_value_ignored_for_ordinary_company(self):
        self.company.rs_form15_is_leasing_company = False
        self._leased()
        self.assertAlmostEqual(self._rows().average_value, 1000)

    def test_lease_out_value_not_declared_after_sale(self):
        self.company.rs_form15_is_leasing_company = True
        self._dispose(self._leased(), '2022-06-30')
        self.assertFalse(self._rows())

    def test_lease_out_value_not_declared_before_acquisition(self):
        self.company.rs_form15_is_leasing_company = True
        self._leased(acquired='2026-03-01')
        self.assertFalse(self._rows())

    def test_lease_out_value_halved_in_sale_year(self):
        self.company.rs_form15_is_leasing_company = True
        self._dispose(self._leased(), '2025-06-30')
        self.assertAlmostEqual(self._rows().average_value, 25000)

    def test_explanation_matches_lease_out_row(self):
        self.company.rs_form15_is_leasing_company = True
        self._leased()
        row = self._rows()
        self.assertAlmostEqual(row.average_value, 50000)
        self.assertAlmostEqual(row._explain()['sources'][0]['average'], 50000)


    def test_archived_sold_asset_counts_in_its_sale_year(self):
        """Odoo archives only closed assets, which are exactly the ones that still had a
        value in their sale year."""
        car = self._asset('Sold car', CARS, 1000)
        self._dispose(car, '2025-06-30')
        car.active = False
        row = self._rows()
        self.assertAlmostEqual(row.average_value, 500)
        self.assertIn('Sold car', [source['name'] for source in row._explain()['sources']])


    # ---- art. 202(2): audited IFRS revaluation, decided per declared object ----------

    AUDITED = {'rs_form15_revaluation_model_applied': True, 'rs_form15_last_audit_date': '2024-03-31'}

    def _pipeline_group(self, audited_both):
        group = self.env['account.asset.group'].create({'name': 'Gori pipeline'})
        self._asset('Pipe A', PIPELINES, 1000, acquired='2001-05-01', asset_group_id=group.id, **self.AUDITED)
        self._asset('Pipe B', PIPELINES, 1000, acquired='2001-05-01', asset_group_id=group.id,
                    **(self.AUDITED if audited_both else {}))

    def test_partly_audited_group_is_one_row(self):
        self._pipeline_group(audited_both=False)
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertEqual(row.revaluation_coefficient_id.coefficient, 2.0)
        self.assertIn('IFRS', row.warning)

    def test_fully_audited_group_takes_coefficient_one(self):
        self._pipeline_group(audited_both=True)
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertEqual(row.revaluation_coefficient_id.coefficient, 1.0)
        self.assertNotIn('IFRS', row.warning or '')

    def test_flag_on_movable_asset_does_not_split_the_row(self):
        self._asset('Car A', CARS, 1000, **self.AUDITED)
        self._asset('Car B', CARS, 1000)
        row = self._rows()
        self.assertEqual(len(row), 1)
        self.assertAlmostEqual(row.average_value, 2000)


    # ---- column 12 typed by hand ---------------------------------------------------

    def test_typed_advance_kept_without_previous_year(self):
        """First year in Odoo: column 12 comes from paper, and Generate must not wipe it."""
        self._asset('Poti office', BUILDINGS, 1000)
        self._asset('Laptop', COMPUTERS, 3000)
        for row in self._rows():
            row.advance_amount = 123
        self.assertEqual(self._rows().mapped('advance_amount'), [123, 123])

    def test_previous_year_still_wins_over_typed_advance(self):
        office = self._asset('Poti office', BUILDINGS, 1000)
        self._previous_year(({'asset_id': office.id}, 1000))
        self._rows().advance_amount = 123
        self.assertAlmostEqual(self._rows().advance_amount, 10.0)


    def test_name_is_read_in_the_company_language(self):
        """Column 2 goes to rs.ge; it must not depend on who pressed Generate."""
        self.env['res.lang']._activate_lang('ka_GE')
        self.company.partner_id.lang = 'ka_GE'
        pipe = self._asset('Gas pipeline', PIPELINES, 1000)
        pipe.with_context(lang='ka_GE').name = 'გაზსადენი'
        rows = self._rows(self.declaration.with_context(lang='en_US'))
        self.assertEqual(rows.name, 'გაზსადენი')


    def test_missing_year_is_created_for_generation(self):
        """rs.ge adds one option per year; a new year must not stop the declaration."""
        later = self.env['rs.form15.declaration'].create({'company_id': self.company.id, 'date_from': '2031-01-01'})
        self._asset('New office', BUILDINGS, 1000, acquired='2031-03-01')
        row = self._rows(later)
        self.assertEqual(row.acquisition_year_id.code, '2031')
        self.assertIn('2031', row.warning)

    def test_2026_option_is_shipped(self):
        self.assertTrue(self.env['rs.form15.year']._for_year(2026))


    def test_fully_depreciated_leased_asset_still_declared(self):
        """Fully depreciated is not sold: the asset still exists and is still leased out."""
        self.company.rs_form15_is_leasing_company = True
        asset = self._leased()
        asset.main_variant_id.already_depreciated_amount_import = 1000
        self.assertAlmostEqual(asset._rs_form15_book_value(fields.Date.to_date('2025-12-31')), 0)
        self.assertAlmostEqual(self._rows().average_value, 50000)

    def test_auto_created_year_survives_a_later_data_file(self):
        """The next release ships the year in the CSV under this xmlid; it must find it."""
        later = self.env['rs.form15.declaration'].create({'company_id': self.company.id, 'date_from': '2031-01-01'})
        self._asset('New office', BUILDINGS, 1000, acquired='2031-03-01')
        option = self._rows(later).acquisition_year_id
        self.assertEqual(self.env.ref('gec_property_tax_report.year_2031'), option)

    def test_archived_year_option_is_reused_not_duplicated(self):
        self.env['rs.form15.year'].create({'code': '2032', 'name': '2032', 'active': False})
        option = self.env['rs.form15.year']._for_year(2032, create=True)
        self.assertEqual(option.code, '2032')

    def test_typed_advance_kept_when_previous_year_has_no_rows(self):
        self.env['rs.form15.declaration'].create({'company_id': self.company.id, 'date_from': '2024-01-01'})
        self._asset('Laptop', COMPUTERS, 3000)
        self._rows().advance_amount = 123
        self.assertAlmostEqual(self._rows().advance_amount, 123)

    def _step6(self, row):
        return next(step for step in row._explain()['steps'] if step['code'] == '6')['detail']

    def test_explanation_counts_archived_assets(self):
        car = self._asset('Sold car', CARS, 1000)
        self._dispose(car, '2025-06-30')
        car.active = False
        self.assertIn('1 asset', self._step6(self._rows()))

    def test_lease_out_label_names_how_many_assets_it_covers(self):
        """A row mixing a frozen asset with a normal one must say so, not relabel the row."""
        self.company.rs_form15_is_leasing_company = True
        group = self.env['account.asset.group'].create({'name': 'Excavator fleet'})
        self._leased(asset_group_id=group.id)
        self._asset('Spare excavator', LEASED_MOVABLE, 1000, asset_group_id=group.id)
        self.assertIn('1 of 2', self._step6(self._rows()))

    def test_long_sold_assets_are_not_read(self):
        """Archived assets are read for their sale year only, not the whole history."""
        old, recent = self._asset('Old car', CARS, 1000), self._asset('Recent car', CARS, 1000)
        self._dispose(old, '2022-06-30')
        self._dispose(recent, '2025-06-30')
        (old | recent).active = False
        assets = self.declaration._part3_assets()
        self.assertNotIn(old, assets)
        self.assertIn(recent, assets)

    def test_plot_link_keeps_land_out_of_part3_even_if_unticked(self):
        land = self._asset('Vake land', CARS, 1000, model_id=self.no_depreciation_model.id)
        self.env['rs.form15.land.plot'].create({
            'name': 'Vake', 'company_id': self.company.id, 'area': 100, 'asset_id': land.id,
            'land_territory_id': self.env.ref('gec_property_tax_report.land_territory_78703').id,
            'land_type_id': self.env.ref('gec_property_tax_report.land_type_33').id,
        })
        land.rs_form15_excluded = False
        self.assertNotIn(land, self.declaration._part3_assets())

@tagged('post_install', '-at_install')
class TestForm15Activation(TestAccountAssetCommon):
    """Activating depreciation closes a no-depreciation asset and creates a new one;
    the property tax tags must follow, and the value must not be counted twice."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = cls.env['account.asset.group'].create({'name': 'Batumi tower'})
        cls.cip = cls.create_asset(value=10000, method='no_depreciation', acquisition_date='2020-01-01')
        cls.cip.write({
            'name': 'Tower shell',
            'asset_group_id': cls.site.id,
            'rs_form15_property_type_id': cls.env.ref(CONSTRUCTION).id,
            'rs_form15_territory_id': cls.env.ref(POTI).id,
            'rs_form15_exemption_basis_id': cls.env.ref('gec_property_tax_report.exemption_1').id,
            'rs_form15_exemption_amount': 500,
        })
        cls.cip.validate()
        cls.building_account = cls.company_data['default_account_assets'].copy({'name': 'Buildings'})

    def _activate(self, on='2025-06-30'):
        self.env['asset.modify'].create({
            'asset_variant_id': self.cip.main_variant_id.id,
            'modify_action': 'activate_depreciation',
            'date': fields.Date.to_date(on),
            'new_account_asset_id': self.building_account.id,
            'name': 'Put into use',
        }).activate_depreciation()
        return self.cip.derived_asset_ids

    def test_tags_follow_and_the_type_comes_from_the_new_model(self):
        self.building_account.depreciation_model_id.rs_form15_property_type_id = self.env.ref(BUILDINGS)
        building = self._activate()
        self.assertEqual(len(building), 1)
        self.assertEqual(building.rs_form15_property_type_id, self.env.ref(BUILDINGS))
        self.assertEqual(building.rs_form15_territory_id, self.env.ref(POTI))
        self.assertEqual(building.asset_group_id, self.site)
        self.assertEqual(building.rs_form15_exemption_basis_id, self.cip.rs_form15_exemption_basis_id)
        self.assertFalse(building.rs_form15_exemption_amount)  # would be claimed twice

    def test_without_a_default_the_pre_use_type_is_not_copied(self):
        self.building_account.depreciation_model_id.rs_form15_property_type_id = False
        building = self._activate()
        self.assertFalse(building.rs_form15_property_type_id)

    def test_activation_year_counts_the_value_once(self):
        """The shell counts until 30 June and the building from then: 10000 at 1 January
        on the shell, 10000 at 31 December on the building, no more."""
        self.building_account.depreciation_model_id.rs_form15_property_type_id = self.env.ref(BUILDINGS)
        building = self._activate()
        opening, closing = fields.Date.to_date('2025-01-01'), fields.Date.to_date('2025-12-31')
        self.assertAlmostEqual(self.cip._rs_form15_book_value(opening), 10000)
        self.assertAlmostEqual(self.cip._rs_form15_book_value(closing), 0)
        self.assertAlmostEqual(building._rs_form15_book_value(opening), 0)
        self.assertLessEqual(building._rs_form15_book_value(closing), 10000)

    def test_reversed_moves_do_not_delay_disposal(self):
        """In a hashed journal a back-dated disposal reverses the later entries instead of
        cancelling them; neither the reversed entry nor its reversal moves the sale."""
        variant = self.cip.main_variant_id

        def entry(on, **extra):
            move = self.env['account.move'].create({
                'move_type': 'entry', 'date': on, **extra,
                'line_ids': [
                    Command.create({'account_id': self.cip.account_asset_id.id, 'debit': 0, 'credit': 1}),
                    Command.create({'account_id': self.building_account.id, 'debit': 1, 'credit': 0}),
                ],
            })
            move.action_post()
            return move
        disposal, late = entry('2024-06-30'), entry('2025-12-31')
        reversal = entry('2025-12-31', reversed_entry_id=late.id)
        (disposal | late | reversal).asset_variant_id = variant
        variant.state = 'close'
        self.assertEqual(self.env['account.asset']._rs_form15_disposal_date(variant),
                         fields.Date.to_date('2024-06-30'))

    def test_cancelled_moves_do_not_delay_disposal(self):
        """With a restrictive audit trail a back-dated disposal cancels the later entries
        instead of deleting them; core then dates the disposal on the last cancelled one."""
        variant = self.cip.main_variant_id

        def entry(on):
            return self.env['account.move'].create({
                'move_type': 'entry',
                'date': on,
                'line_ids': [
                    Command.create({'account_id': self.cip.account_asset_id.id, 'debit': 0, 'credit': 1}),
                    Command.create({'account_id': self.building_account.id, 'debit': 1, 'credit': 0}),
                ],
            })
        disposal, late = entry('2024-06-30'), entry('2025-12-31')
        disposal.action_post()
        late.button_cancel()
        (disposal | late).asset_variant_id = variant
        variant.state = 'close'
        self.assertEqual(variant.disposal_date, fields.Date.to_date('2025-12-31'), "core counts the cancelled entry")
        self.assertEqual(self.env['account.asset']._rs_form15_disposal_date(variant),
                         fields.Date.to_date('2024-06-30'))
        self.assertAlmostEqual(self.cip._rs_form15_book_value(fields.Date.to_date('2024-12-31')), 0)
