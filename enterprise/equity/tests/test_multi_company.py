from odoo.exceptions import ValidationError

from odoo.addons.equity.tests.common import TestEquityCommon


class TestEquityMultiCompany(TestEquityCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.contact_1.company_id = cls.env.company.id
        cls.company_2 = cls.env['res.company'].create({'name': 'Company 2'})
        cls.contact_2.company_id = cls.company_2.id

    def _create_transaction(self, subscriber=None, seller=None, transaction_type='issuance', securities=100):
        vals = {
            'partner_id': self.company.id,
            'transaction_type': transaction_type,
            'securities': securities,
            'security_price': 10,
            'security_class_id': self.option_class_1.id,
        }
        if subscriber:
            vals['subscriber_id'] = subscriber.id
        if seller:
            vals['seller_id'] = seller.id
        return self.env['equity.transaction'].create(vals)

    def test_transaction_issuance_company_rules(self):
        """subscriber_id is unrestricted while partner_id has no company scope.
        It is restricted to that company's hierarchy once one is set."""
        self.company.company_id = False

        # partner_id has no scope: any subscriber is allowed, whatever company they belong to
        self._create_transaction(subscriber=self.contact_1)
        self._create_transaction(subscriber=self.contact_2)

        self.company.company_id = self.env.company
        # contact_1 (same company) stays a valid subscriber
        self._create_transaction(subscriber=self.contact_1)
        # contact_2 belongs to an unrelated company: rejected as subscriber
        with self.assertRaisesRegex(ValidationError, 'not belong to a company compatible with this transaction'):
            self._create_transaction(subscriber=self.contact_2)

    def test_transaction_transfer_company_rules(self):
        """seller_id is unrestricted while partner_id has no company scope.
        It is restricted to that company's hierarchy once one is set."""
        self.company.company_id = False

        # stock both contacts up front so none of the transfers below ever run short, regardless of company
        self._create_transaction(subscriber=self.contact_1, securities=1000)
        self._create_transaction(subscriber=self.contact_2, securities=1000)

        # partner_id has no scope: any seller is allowed, whatever company they belong to
        self._create_transaction(seller=self.contact_1, transaction_type='transfer')
        self._create_transaction(seller=self.contact_2, transaction_type='transfer')

        self.company.company_id = self.env.company
        # contact_1 (same company) stays a valid seller
        self._create_transaction(seller=self.contact_1, transaction_type='transfer')
        # contact_2 belongs to an unrelated company: rejected as seller
        with self.assertRaisesRegex(ValidationError, 'not belong to a company compatible with this transaction'):
            self._create_transaction(seller=self.contact_2, transaction_type='transfer')
        # a valid seller (contact_1) does not shield an invalid subscriber (contact_2) on the same transaction
        with self.assertRaisesRegex(ValidationError, 'not belong to a company compatible with this transaction'):
            self._create_transaction(seller=self.contact_1, subscriber=self.contact_2, transaction_type='transfer')

    def test_ubo_company_rules(self):
        """holder_id is unrestricted while partner_id has no company scope.
        It is restricted to that company's hierarchy once one is set."""
        self.company.company_id = False
        # partner_id has no scope: holder from any company is allowed
        ubos = self.env['equity.ubo'].create([{
            'partner_id': self.company.id,
            'holder_id': contact.id,
            'start_date': '2010-01-01',
        } for contact in (self.contact_1, self.contact_2)])
        # unlink: the unique (partner_id, holder_id) constraint would otherwise clash with the scoped block below
        ubos.unlink()

        self.company.company_id = self.env.company
        # partner_id now scoped to the current company: contact_1 (same company) stays a valid holder
        self.env['equity.ubo'].create({
            'partner_id': self.company.id,
            'holder_id': self.contact_1.id,
            'start_date': '2010-01-01',
        })
        # contact_2 belongs to an unrelated company: rejected as holder
        with self.assertRaisesRegex(ValidationError, 'not belong to a company compatible with this record'):
            self.env['equity.ubo'].create({
                'partner_id': self.company.id,
                'holder_id': self.contact_2.id,
                'start_date': '2010-01-01',
            })
