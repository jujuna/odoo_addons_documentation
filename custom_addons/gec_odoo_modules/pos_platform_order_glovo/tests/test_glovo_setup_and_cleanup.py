from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGlovoProviderSetup(TransactionCase):

    def _glovo_accounting(self, company):
        return (
            self.env['account.journal'].search([('code', '=', 'GLOVO'), ('company_id', '=', company.id)]),
            self.env['pos.payment.method'].search([('journal_id.code', '=', 'GLOVO'), ('company_id', '=', company.id)]),
            self.env['product.pricelist'].search([('name', '=', 'Glovo'), ('company_id', 'in', [False, company.id])]),
        )

    def test_reinstall_reuses_journal_payment_method_and_pricelist(self):
        Provider = self.env['platform.order.provider']
        provider = self.env.ref('pos_platform_order_glovo.platform_order_provider_glovo')
        company = provider.company_id
        Provider._setup_provider('glovo')  # the install hook
        installed = self._glovo_accounting(company)
        self.assertEqual([len(records) for records in installed], [1, 1, 1])
        Provider._setup_provider('glovo')
        self.assertEqual(self._glovo_accounting(company), installed, "a second setup creates nothing")

        Provider._remove_provider('glovo')  # the uninstall hook
        self.assertEqual(provider.code, 'none')
        self.assertTrue(all(records.exists() for records in installed), "uninstall keeps them: they can carry payments")

        # reinstall: the provider gets its code back from the data file, then the install hook runs again
        provider.write({'code': 'glovo', 'default_payment_method_id': False, 'default_pricelist_id': False})
        Provider._setup_provider('glovo')
        self.assertEqual(self._glovo_accounting(company), installed)
        journal, payment_method, pricelist = installed
        self.assertEqual((provider.default_payment_method_id, provider.default_pricelist_id), (payment_method, pricelist))
        self.assertEqual(payment_method.journal_id, journal)


@tagged('post_install', '-at_install')
class TestGlovoEventCleanup(TransactionCase):

    def _event(self, order_id, state, days_old):
        event = self.env['glovo.event'].create({
            'event_type': 'dispatched', 'glovo_order_id': order_id, 'state': state, 'payload': '{}',
        })
        self.env.cr.execute(
            "UPDATE glovo_event SET write_date = %s WHERE id = %s",
            [fields.Datetime.now() - timedelta(days=days_old), event.id],
        )
        return event

    def _remaining_after_cleanup(self, events):
        self.env.invalidate_all()
        self.env['glovo.event']._gc_processed_events()
        return events.exists().mapped('glovo_order_id')

    def test_old_events_are_deleted_in_any_state(self):
        events = (
            self._event('C1', 'processed', 100) | self._event('C2', 'processed', 80)
            | self._event('C3', 'failed', 400) | self._event('C4', 'received', 400)
        )
        self.assertEqual(self._remaining_after_cleanup(events), ['C2'])

    def test_retention_comes_from_the_system_parameter(self):
        events = self._event('C5', 'processed', 40) | self._event('C6', 'processed', 20)
        self.env['ir.config_parameter'].set_int('glovo_base.event_retention_days', 30)
        self.assertEqual(self._remaining_after_cleanup(events), ['C6'])
        self.env['ir.config_parameter'].set_int('glovo_base.event_retention_days', 0)
        self.assertEqual(self._remaining_after_cleanup(self._event('C7', 'processed', 400)), ['C7'])
