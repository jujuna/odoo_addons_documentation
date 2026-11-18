/** @odoo-module */

import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { patch } from "@web/core/utils/patch";

patch(AccountReportFilters.prototype, {
    async OnSelectCurrency(currency) {
        const wasSelected = currency.selected;
        const options = this.controller.cachedFilterOptions;
        const currencies = options.currencies || [];
        for (const c of currencies) {
            c.selected = false;
        }
        currency.selected = !wasSelected;
        if (currency.selected) {
            options.selected_currencies_id = currency.id;
            options.selected_currencies = currency.name;
        } else {
            options.selected_currencies_id = false;
            options.selected_currencies = false;
        }
        await this.controller.reload('currencies', options);
    },
});
