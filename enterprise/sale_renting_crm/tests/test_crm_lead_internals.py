# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.addons.crm.tests import common as crm_common
from odoo.tests import tagged, Form, users


@tagged('at_install', '-post_install')  # LEGACY at_install
class TestLead(crm_common.TestCrmCommon):

    @users('user_sales_leads')
    def test_propagation_lead_user_to_rental_order(self):
        """ Priority for default salesperson on rental order from a lead should be
        1) The one on the lead 2) The one on the partner 3) The current user """
        SaleOrder = self.env['sale.order']
        lead = self.env['crm.lead'].browse(self.lead_1.ids)
        partner = self.contact_1
        lead.partner_id = partner

        lead.user_id = self.user_sales_manager
        partner.user_id = self.user_sales_salesman
        rental_order_form = Form(SaleOrder.with_context(lead._prepare_opportunity_quotation_context()))
        rental_order = rental_order_form.save()
        self.assertEqual(rental_order.user_id, self.user_sales_manager, 'The salesperson of the lead is set and should be propagated on the rental order.')

        lead.user_id = False
        rental_order_form = Form(SaleOrder.with_context(lead._prepare_opportunity_quotation_context()))
        rental_order = rental_order_form.save()
        self.assertEqual(rental_order.user_id, self.user_sales_salesman, 'The salesperson of contact is set and should be propagated on the rental order.')

        partner.user_id = False
        rental_order_form = Form(SaleOrder.with_context(lead._prepare_opportunity_quotation_context()))
        rental_order = rental_order_form.save()
        self.assertEqual(rental_order.user_id, self.user_sales_leads, 'The salesperson of the current user should be propagated on the rental order.')

    @users('user_sales_leads')
    def test_rental_and_sale_fields(self):
        lead = self.env['crm.lead'].browse(self.lead_1.ids)
        self.contact_1.property_product_pricelist = self.env['product.pricelist'].sudo().create({
            'name': 'Test Pricelist',
        })
        sale_product = self.env['product.product'].sudo().create({
            'list_price': 100, 'name': 'Product', 'sale_ok': True, 'type': 'consu'
        })
        rental_product = sale_product.copy({'name': 'Rent Product', 'rent_periodicity': 'days'})

        # As it is an "at_install" test, the country of the company is not yet set
        # and it is requested by "account.tax" and "account.tax.group".
        self.env.company.sudo().write({'country_id': self.env.ref('base.us')})
        tax_su = self.env['account.tax'].sudo().create({
            'name': 'Tax',
            'amount': 21,
            'amount_type': 'percent',
            'tax_group_id': self.env['account.tax.group'].sudo().create({
                'name': 'Tax Group',
                'company_id': self.env.company.id,
            }).id,
        })

        base_order_vals = {'opportunity_id': lead.id, 'partner_id': self.contact_1.id}

        rental_order_vals = {
            **base_order_vals,
            'rental_start_date': fields.Datetime.now(),
            'rental_return_date': fields.Datetime.now() + relativedelta(days=1),
            'order_line': [(0, 0, {'product_id': rental_product.id, 'product_uom_qty': 2, 'tax_ids': tax_su.ids})],
        }

        orders = self.env['sale.order'].create([
            dict(rental_order_vals),
            dict(rental_order_vals),
            dict(rental_order_vals),
        ])
        orders[0:2].action_confirm()
        self.env.flush_all()

        self.assertEqual(lead.rental_quotation_count, 1)
        self.assertEqual(lead.rental_order_count, 2)
        # lead.rental_amount_total = 2 order lines * 2 products * (price without tax + 21% of tax on the price)
        self.assertEqual(lead.rental_amount_total, 2 * 2 * (100 + 21))

        # Check that sale_order_count and, quotation_count and sale_amount_total
        # fields on the lead does not include rental quotations / orders
        sale_order_vals = {
            **base_order_vals,
            'order_line': [(0, 0, {'product_id': sale_product.id, 'product_uom_qty': 2, 'tax_ids': tax_su.ids})],
        }
        orders = self.env['sale.order'].create([sale_order_vals, sale_order_vals])
        self.assertEqual(len(lead.order_ids), 5, "'order_ids' contains all the linked orders(rental or not)")
        self.assertEqual(lead.quotation_count, 2, "'quotation_count' should exclude data of rental quotations")
        self.assertEqual(lead.sale_order_count, 0, "'sale_order_count' should exclude data of rental orders")
        self.assertEqual(lead.sale_amount_total, 0, "'sale_amount_total' should exclude data of rental orders")
        orders[1].action_confirm()
        self.assertEqual(lead.quotation_count, 1, "there should be only one regular(non rental) quotation left")
        self.assertEqual(lead.sale_order_count, 1, "there should be one regular(non rental) sale order(s)")
        # lead.sale_amount_total = 2 products * (price without tax + 21% of tax on the price)
        self.assertEqual(lead.sale_amount_total, 2 * (100 + 21), "should give total for the regular(non rental) sale order(s) only")

        # Check that all the rental related computations are not affected
        self.assertEqual(lead.rental_quotation_count, 1)
        self.assertEqual(lead.rental_order_count, 2)
        # lead.rental_amount_total = 2 order lines * 2 products * (price without tax + 21% of tax on the price)
        self.assertEqual(lead.rental_amount_total, 2 * 2 * (100 + 21))

    @users('user_sales_leads')
    def test_action_view_sale_quotation_excludes_rental_quotations(self):
        sale_product, rental_product = self.env['product.product'].sudo().create([
            {'name': 'Product'},
            {'name': 'Rent Product', 'rent_periodicity': 'days'},
        ])
        regular_quotation, rental_quotation = self.env['sale.order'].create([
            {
                'opportunity_id': self.lead_1.id,
                'partner_id': self.contact_1.id,
                'order_line': [(0, 0, {'product_id': sale_product.id, 'product_uom_qty': 1})],
            },
            {
                'opportunity_id': self.lead_1.id,
                'partner_id': self.contact_1.id,
                'rental_start_date': fields.Datetime.now(),
                'rental_return_date': fields.Datetime.now() + relativedelta(days=1),
                'order_line': [(0, 0, {'product_id': rental_product.id, 'product_uom_qty': 1})],
            },
        ])
        action = self.lead_1.action_view_sale_quotation()
        visible_orders = self.env['sale.order'].search_fetch(action['domain'], ['id'])
        self.assertEqual(visible_orders.ids, [regular_quotation.id])
        self.assertNotIn(rental_quotation.id, visible_orders.ids)
