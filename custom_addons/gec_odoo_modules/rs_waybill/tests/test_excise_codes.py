"""Excise (akciz) code validity, which must answer for today on every read, and the RS catalog sync,
which must not rewrite validity data RS did not send.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestExciseCodeValidity(RsWaybillCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ExciseCode = cls.env['rs.excise.code']
        today = fields.Date.context_today(cls.ExciseCode)
        cls.today = today
        cls.live = cls.ExciseCode.create({
            'rs_id': 900001, 'name': 'Live code',
            'active_from': today - timedelta(days=30),
            'active_until': today + timedelta(days=30),
        })
        cls.open_ended = cls.ExciseCode.create({
            'rs_id': 900002, 'name': 'No expiry',
            'active_from': today - timedelta(days=30),
        })
        cls.expired = cls.ExciseCode.create({
            'rs_id': 900003, 'name': 'Expired code',
            'active_from': today - timedelta(days=60),
            'active_until': today - timedelta(days=1),
        })
        cls.future = cls.ExciseCode.create({
            'rs_id': 900004, 'name': 'Future code',
            'active_from': today + timedelta(days=1),
        })

    def test_live_code_is_active(self):
        self.assertTrue(self.live.is_currently_active)

    def test_empty_active_until_means_no_expiry(self):
        self.assertTrue(self.open_ended.is_currently_active)

    def test_expired_code_is_not_active(self):
        self.assertFalse(self.expired.is_currently_active)

    def test_future_code_is_not_active_yet(self):
        self.assertFalse(self.future.is_currently_active)

    def test_boundary_days_are_inclusive(self):
        """A code valid [today, today] is active today: both ends are inclusive."""
        code = self.ExciseCode.create({
            'rs_id': 900005, 'name': 'One-day code',
            'active_from': self.today, 'active_until': self.today,
        })
        self.assertTrue(code.is_currently_active)

    def test_value_tracks_the_calendar_not_the_last_write(self):
        """A stored compute would freeze at write time; reading the same record as if tomorrow must
        change the answer."""
        code = self.ExciseCode.create({
            'rs_id': 900006, 'name': 'Expires tonight',
            'active_from': self.today - timedelta(days=10),
            'active_until': self.today,
        })
        self.assertTrue(code.is_currently_active)

        tomorrow = self.today + timedelta(days=1)
        with patch.object(fields.Date, 'context_today', return_value=tomorrow):
            code.invalidate_recordset(['is_currently_active'])
            self.assertFalse(
                code.is_currently_active,
                "the code expired overnight but still reads as active — the value is "
                "frozen instead of tracking today")

    def test_search_active_finds_only_live_codes(self):
        found = self.ExciseCode.search([
            ('is_currently_active', '=', True),
            ('rs_id', '>=', 900001), ('rs_id', '<=', 900004),
        ])
        self.assertEqual(set(found.ids), {self.live.id, self.open_ended.id})

    def test_search_inactive_is_the_exact_complement(self):
        found = self.ExciseCode.search([
            ('is_currently_active', '=', False),
            ('rs_id', '>=', 900001), ('rs_id', '<=', 900004),
        ])
        self.assertEqual(set(found.ids), {self.expired.id, self.future.id})

    def test_search_not_equal_true_matches_inactive(self):
        found = self.ExciseCode.search([
            ('is_currently_active', '!=', True),
            ('rs_id', '>=', 900001), ('rs_id', '<=', 900004),
        ])
        self.assertEqual(set(found.ids), {self.expired.id, self.future.id})

    def test_search_and_compute_agree(self):
        """Whatever the domain returns must match what reading the field says."""
        codes = self.ExciseCode.search([('rs_id', '>=', 900001), ('rs_id', '<=', 900004)])
        by_search = set(codes.filtered_domain([('is_currently_active', '=', True)]).ids)
        by_read = set(codes.filtered('is_currently_active').ids)
        self.assertEqual(by_search, by_read)

    def test_unsupported_operator_is_refused(self):
        """Called directly: the domain optimiser rejects a non-boolean operator before the search
        method, so the guard is only reachable here."""
        with self.assertRaises(UserError):
            self.ExciseCode._search_is_currently_active('like', True)


@tagged('post_install', '-at_install')
class TestAkcizCatalogSync(RsWaybillCommon):
    """action_update_rs_products, steps 1-3, with the RS responses stubbed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ExciseCode = cls.env['rs.excise.code']

    def _sync(self, akciz_rows, bar_codes=None):
        Service = type(self.service)
        with patch.object(Service, 'get_akciz_codes', return_value=akciz_rows), \
             patch.object(Service, 'get_bar_codes', return_value=bar_codes or []):
            self.env['product.product'].action_update_rs_products()

    def test_blank_start_date_does_not_move_an_existing_window(self):
        """A row with no START_DATE must not move active_from forward on every run."""
        original = fields.Date.context_today(self.ExciseCode) - timedelta(days=365)
        code = self.ExciseCode.create({
            'rs_id': 910001, 'name': 'Historic code', 'active_from': original,
        })

        self._sync([{'ID': '910001', 'TITLE': 'Historic code', 'START_DATE': ''}])

        self.assertEqual(code.active_from, original,
                         "a re-sync moved active_from even though RS sent no START_DATE")

    def test_start_date_from_rs_is_applied(self):
        """When RS does send a start date, it lands."""
        code = self.ExciseCode.create({
            'rs_id': 910002, 'name': 'Code', 'active_from': '2020-01-01',
        })

        self._sync([{'ID': '910002', 'TITLE': 'Code', 'START_DATE': '2026-03-15'}])

        self.assertEqual(code.active_from, fields.Date.to_date('2026-03-15'))

    def test_new_code_without_start_date_still_gets_one(self):
        """active_from is required: the create path must default it."""
        self._sync([{'ID': '910003', 'TITLE': 'Brand new', 'START_DATE': ''}])

        code = self.ExciseCode.search([('rs_id', '=', 910003)])
        self.assertTrue(code)
        self.assertEqual(code.active_from, fields.Date.context_today(self.ExciseCode))

    def test_unchanged_code_is_not_rewritten(self):
        """Dates are compared as dates; compared as strings every code would look changed."""
        code = self.ExciseCode.create({
            'rs_id': 910004, 'name': 'Stable code',
            'active_from': '2026-01-01', 'active_until': '2026-12-31',
        })
        before = code.write_date

        self._sync([{'ID': '910004', 'TITLE': 'Stable code',
                     'START_DATE': '2026-01-01', 'END_DATE': '2026-12-31'}])

        self.assertEqual(code.write_date, before,
                         "an unchanged code was written anyway")

    def test_changed_title_is_written(self):
        code = self.ExciseCode.create({
            'rs_id': 910005, 'name': 'Old title', 'active_from': '2026-01-01',
        })

        self._sync([{'ID': '910005', 'TITLE': 'New title', 'START_DATE': '2026-01-01'}])

        self.assertEqual(code.name, 'New title')

    def test_barcode_matching_an_excise_title_reuses_the_existing_product(self):
        """A barcode whose name matches an excise title reuses that code's product instead of
        creating a second one."""
        today = fields.Date.context_today(self.ExciseCode)
        self._sync(
            [{'ID': '910006', 'TITLE': 'Excise widget', 'START_DATE': str(today)}],
            [{'CODE': 'BC-910006', 'NAME': 'Excise widget'}],
        )

        code = self.ExciseCode.search([('rs_id', '=', 910006)])
        products = self.env['product.product'].search([('rs_excise_id', '=', code.id)])
        self.assertEqual(len(products), 1, "two products created for one excise code")
        self.assertEqual(products.barcode, 'BC-910006',
                         "the barcode should land on the existing product")

    def test_expired_codes_get_no_product(self):
        """Step 2 iterates active codes only, so an expired code gets no product."""
        past = fields.Date.context_today(self.ExciseCode) - timedelta(days=10)
        self._sync([{'ID': '910007', 'TITLE': 'Long gone',
                     'START_DATE': '2020-01-01', 'END_DATE': str(past)}])

        code = self.ExciseCode.search([('rs_id', '=', 910007)])
        self.assertTrue(code, "the code itself is still catalogued")
        self.assertFalse(code.is_currently_active)
        self.assertFalse(self.env['product.product'].search([('rs_excise_id', '=', code.id)]))
