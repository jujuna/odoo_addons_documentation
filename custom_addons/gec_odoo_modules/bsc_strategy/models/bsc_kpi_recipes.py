# -*- coding: utf-8 -*-
"""Ready-made data sources, offered only when the app they read is installed; become ``bsc.kpi.source`` on first use.
Rules: reporting-model money (company currency); measure-meaning date, not creation;
credit notes netted off revenue; no cancelled or draft."""
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

CURRENCY = 'currency'   # replaced by the company currency code at connection time

RECIPES = [
    {
        'key': 'sale_amount', 'module': 'sale', 'app': _lt("Sales"),
        'name': _lt("Confirmed sales (untaxed)"),
        'description': _lt("Untaxed value of confirmed sales order lines, in the company "
                           "currency, by order date. Quotations and cancelled orders are "
                           "not counted."),
        'model': 'sale.report', 'domain': [('state', '=', 'sale')],
        'aggregate': 'sum', 'value_field': 'price_subtotal', 'date_field': 'date',
        'uom': CURRENCY, 'direction': 'higher_better',
    },
    {
        'key': 'sale_orders', 'module': 'sale', 'app': _lt("Sales"),
        'name': _lt("Number of confirmed sales orders"),
        'description': _lt("Sales orders confirmed in the period, counted by order date."),
        'model': 'sale.order', 'domain': [('state', '=', 'sale')],
        'aggregate': 'count', 'date_field': 'date_order',
        'uom': _lt("orders"), 'direction': 'higher_better',
    },
    {
        'key': 'sale_quotation_conversion', 'module': 'sale', 'app': _lt("Sales"),
        'name': _lt("Quotation conversion rate (%)"),
        'description': _lt("Share of the quotations created in the period that were "
                           "confirmed. Cancelled quotations count as not converted."),
        'model': 'sale.order', 'domain': [('state', 'in', ['draft', 'sent', 'sale', 'cancel'])],
        'aggregate': 'ratio', 'ratio_domain': [('state', '=', 'sale')],
        'date_field': 'create_date', 'uom': '%', 'direction': 'higher_better',
    },
    {
        'key': 'invoiced_revenue', 'module': 'account', 'app': _lt("Accounting"),
        'name': _lt("Invoiced revenue (untaxed, net of credit notes)"),
        'description': _lt("Untaxed amount of posted customer invoices minus credit notes, "
                           "in the company currency, by invoice date."),
        'model': 'account.invoice.report',
        'domain': [('state', '=', 'posted'), ('move_type', 'in', ['out_invoice', 'out_refund'])],
        'aggregate': 'sum', 'value_field': 'price_subtotal', 'date_field': 'invoice_date',
        'uom': CURRENCY, 'direction': 'higher_better',
    },
    {
        'key': 'customer_invoices', 'module': 'account', 'app': _lt("Accounting"),
        'name': _lt("Number of customer invoices"),
        'description': _lt("Posted customer invoices, by invoice date. Credit notes are not "
                           "counted."),
        'model': 'account.move',
        'domain': [('state', '=', 'posted'), ('move_type', '=', 'out_invoice')],
        'aggregate': 'count', 'date_field': 'invoice_date',
        'uom': _lt("invoices"), 'direction': 'higher_better',
    },
    {
        'key': 'vendor_bills', 'module': 'account', 'app': _lt("Accounting"),
        'name': _lt("Vendor bills (untaxed, net of refunds)"),
        'description': _lt("Untaxed amount of posted vendor bills minus vendor credit notes, "
                           "in the company currency, by bill date."),
        'model': 'account.invoice.report',
        'domain': [('state', '=', 'posted'), ('move_type', 'in', ['in_invoice', 'in_refund'])],
        'aggregate': 'sum', 'value_field': 'price_subtotal', 'date_field': 'invoice_date',
        # The report signs purchases negative; a cost reads better as positive.
        'multiply_by': -1.0, 'uom': CURRENCY, 'direction': 'lower_better',
    },
    {
        'key': 'crm_new_leads', 'module': 'crm', 'app': _lt("CRM"),
        'name': _lt("New leads and opportunities"),
        'description': _lt("Leads and opportunities created in the period, including the "
                           "ones that were later lost."),
        'model': 'crm.lead', 'domain': [], 'include_archived': True,
        'aggregate': 'count', 'date_field': 'create_date',
        'uom': _lt("leads"), 'direction': 'higher_better',
    },
    {
        'key': 'crm_won', 'module': 'crm', 'app': _lt("CRM"),
        'name': _lt("Won opportunities"),
        'description': _lt("Opportunities marked won in the period, by closing date."),
        'model': 'crm.lead', 'domain': [('won_status', '=', 'won')],
        'aggregate': 'count', 'date_field': 'date_closed',
        'uom': _lt("deals"), 'direction': 'higher_better',
    },
    {
        'key': 'crm_won_revenue', 'module': 'crm', 'app': _lt("CRM"),
        'name': _lt("Expected revenue of won opportunities"),
        'description': _lt("Sum of the expected revenue of the opportunities won in the "
                           "period, by closing date, in the company currency."),
        'model': 'crm.lead', 'domain': [('won_status', '=', 'won')],
        'aggregate': 'sum', 'value_field': 'expected_revenue', 'date_field': 'date_closed',
        'uom': CURRENCY, 'direction': 'higher_better',
    },
    {
        'key': 'crm_win_rate', 'module': 'crm', 'app': _lt("CRM"),
        'name': _lt("Win rate (%)"),
        'description': _lt("Of the opportunities closed in the period (won or lost), the "
                           "share that was won."),
        'model': 'crm.lead', 'domain': [('won_status', 'in', ['won', 'lost'])],
        'include_archived': True,
        'aggregate': 'ratio', 'ratio_domain': [('won_status', '=', 'won')],
        'date_field': 'date_closed', 'uom': '%', 'direction': 'higher_better',
    },
    {
        'key': 'purchase_amount', 'module': 'purchase', 'app': _lt("Purchase"),
        'name': _lt("Confirmed purchases (untaxed)"),
        'description': _lt("Untaxed value of confirmed purchase orders, in the company "
                           "currency, by confirmation date."),
        'model': 'purchase.report', 'domain': [('state', '=', 'purchase')],
        'aggregate': 'sum', 'value_field': 'untaxed_total', 'date_field': 'date_approve',
        'uom': CURRENCY, 'direction': 'lower_better',
    },
    {
        'key': 'deliveries_done', 'module': 'stock', 'app': _lt("Inventory"),
        'name': _lt("Deliveries shipped"),
        'description': _lt("Outgoing transfers validated in the period, by date of transfer."),
        'model': 'stock.picking',
        'domain': [('state', '=', 'done'), ('picking_type_code', '=', 'outgoing')],
        'aggregate': 'count', 'date_field': 'date_done',
        'uom': _lt("deliveries"), 'direction': 'higher_better',
    },
    {
        'key': 'receipts_done', 'module': 'stock', 'app': _lt("Inventory"),
        'name': _lt("Receipts received"),
        'description': _lt("Incoming transfers validated in the period, by date of transfer."),
        'model': 'stock.picking',
        'domain': [('state', '=', 'done'), ('picking_type_code', '=', 'incoming')],
        'aggregate': 'count', 'date_field': 'date_done',
        'uom': _lt("receipts"), 'direction': 'higher_better',
    },
    {
        'key': 'mo_done', 'module': 'mrp', 'app': _lt("Manufacturing"),
        'name': _lt("Manufacturing orders completed"),
        'description': _lt("Manufacturing orders marked done in the period, by end date."),
        'model': 'mrp.production', 'domain': [('state', '=', 'done')],
        'aggregate': 'count', 'date_field': 'date_finished',
        'uom': _lt("orders"), 'direction': 'higher_better',
    },
    {
        'key': 'pos_sales', 'module': 'point_of_sale', 'app': _lt("Point of Sale"),
        'name': _lt("Point of Sale sales (tax included)"),
        'description': _lt("Total of paid and posted Point of Sale orders, by order date."),
        'model': 'pos.order', 'domain': [('state', 'in', ['paid', 'done'])],
        'aggregate': 'sum', 'value_field': 'amount_total', 'date_field': 'date_order',
        'uom': CURRENCY, 'direction': 'higher_better',
    },
    {
        'key': 'tasks_done', 'module': 'project', 'app': _lt("Project"),
        'name': _lt("Tasks completed"),
        'description': _lt("Tasks marked done in the period, by the date their status last "
                           "changed. Use \"Only count records where\" to keep one project."),
        'model': 'project.task', 'domain': [('state', '=', '1_done')],
        'aggregate': 'count', 'date_field': 'date_last_stage_update',
        'uom': _lt("tasks"), 'direction': 'higher_better',
    },
]

RECIPES_BY_KEY = {recipe['key']: recipe for recipe in RECIPES}
