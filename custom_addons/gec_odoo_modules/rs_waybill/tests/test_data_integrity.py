"""TIN comparison, external-ref integrity, and where uniqueness is enforced."""

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import RsWaybillCommon


@tagged('post_install', '-at_install')
class TestOurCarrierTinComparison(RsWaybillCommon):
    """RS.GE pads TINs: a padded transporter TIN is still our company."""

    def test_padded_transporter_tin_is_still_our_carrier(self):
        self.env.company.vat = '400999111'
        waybill = self.make_waybill(transporter_tin='400999111 ', transport_type='7')
        self.assertTrue(waybill.is_our_carrier)


@tagged('post_install', '-at_install')
class TestExternalRefVariantIntegrity(RsWaybillCommon):
    """The seller-product mapping picks the product of a waybill line; a mismatched (template,
    variant) pair is refused."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seller = cls.env['res.partner'].create({
            'name': 'Ref Seller', 'vat': '400999333'})
        cls.tmpl_a = cls.env['product.template'].create({'name': 'Template A', 'type': 'consu'})
        cls.tmpl_b = cls.env['product.template'].create({'name': 'Template B', 'type': 'consu'})

    def _ref_vals(self, **overrides):
        vals = {
            'product_id': self.tmpl_a.id,
            'seller_partner_id': self.seller.id,
            'external_barcode': 'EXT-1',
        }
        vals.update(overrides)
        return vals

    def test_a_variant_of_another_product_is_refused(self):
        """The form domain is UI only; an import or ORM write can still pair them."""
        with self.assertRaises(ValidationError) as e:
            self.env['rs.product.external.ref'].create(self._ref_vals(
                variant_id=self.tmpl_b.product_variant_ids[0].id))
        self.assertIn('does not belong to', e.exception.args[0])

    def test_the_products_own_variant_is_accepted(self):
        ref = self.env['rs.product.external.ref'].create(self._ref_vals(
            variant_id=self.tmpl_a.product_variant_ids[0].id))
        self.assertTrue(ref)

    def test_no_variant_is_fine_for_a_single_variant_product(self):
        self.assertTrue(self.env['rs.product.external.ref'].create(self._ref_vals()))

    def test_the_check_also_fires_on_write(self):
        ref = self.env['rs.product.external.ref'].create(self._ref_vals())
        with self.assertRaises(ValidationError):
            ref.variant_id = self.tmpl_b.product_variant_ids[0]

    def test_moving_the_template_away_from_its_variant_is_refused(self):
        """The other direction: keep the variant, repoint the template."""
        ref = self.env['rs.product.external.ref'].create(self._ref_vals(
            variant_id=self.tmpl_a.product_variant_ids[0].id))
        with self.assertRaises(ValidationError):
            ref.product_id = self.tmpl_b


@tagged('post_install', '-at_install')
class TestRsInternalIdUniqueness(RsWaybillCommon):
    """Enforced by the partial unique index alone (a Python check can race between workers)."""

    def test_a_duplicate_rs_id_is_still_rejected(self):
        self.make_waybill(rs_internal_id=950001)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.make_waybill(rs_internal_id=950001)
            self.env.flush_all()

    def test_several_waybills_may_have_no_rs_id(self):
        """The index is partial: unsaved waybills all carry False and must not collide."""
        self.make_waybill()
        self.make_waybill()
        self.env.flush_all()

    def test_distinct_ids_coexist(self):
        self.make_waybill(rs_internal_id=950002)
        self.make_waybill(rs_internal_id=950003)
        self.env.flush_all()
