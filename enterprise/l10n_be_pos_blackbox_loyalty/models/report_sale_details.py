from odoo import models, api

from odoo.addons.l10n_be_pos_blackbox_loyalty.models.pos_session import L10N_BE_VOUCHER_PAYMENTS


class ReportPoint_Of_SaleReport_Saledetails(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    def _get_products_and_taxes_dict(self, line, products, taxes, currency):
        # A gift card / eWallet redemption is a payment, not merchandise: it is
        # reported as a VOUCHER financial and mirrored in the payments table below,
        # so it must not reach the product and tax tables. `_is_refund_order_line`
        # would otherwise route it to the refunds table, where it would read as if
        # goods had been returned and double count against its own payment row.
        if line.order_id.config_id.l10n_be_blackbox_be_id and line._l10n_be_voucher_program_type():
            return products, taxes
        return super()._get_products_and_taxes_dict(line, products, taxes, currency)

    @api.model
    def get_sale_details(self, date_start=False, date_stop=False, config_ids=False, session_ids=False, **kwargs):
        data = super().get_sale_details(
            date_start, date_stop, config_ids, session_ids, **kwargs
        )

        # `l10_be_payments` only exists on the turnover report of a single blackbox
        # session, which makes this a no-op everywhere else.
        payments_per_method = list(data.get("payments_per_method", []))
        for payment in data.get("l10_be_payments", []):
            if payment["id"] not in L10N_BE_VOUCHER_PAYMENTS:
                continue
            amount = payment["amount"]["totalAmount"]
            data["payments"].append({
                'session': False,
                'name': payment["name"],
                'total': amount,
                'cash': False,
                'count': False,
            })
            payments_per_method.append({'name': payment["name"], 'total': amount})
            # The products table is gross of the redemption while `total_paid` (the
            # real payments) and `currency.total_paid` (the order totals) are net of
            # it. Both must move together, the report prints their difference as the
            # cash rounding.
            data["total_paid"] += amount
            data["currency"]["total_paid"] += amount
        data["payments_per_method"] = payments_per_method

        return data
