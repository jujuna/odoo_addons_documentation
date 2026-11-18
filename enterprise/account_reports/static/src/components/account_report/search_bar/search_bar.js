import { Component, onMounted, signal, t, usePlugin, useProps } from "@odoo/owl";

import { AccountReportController } from "@account_reports/components/account_report/controller";


export class AccountReportSearchBar extends Component {
    static template = "account_reports.AccountReportSearchBar";
    props = useProps({
        initialQuery: t.string().optional(),
    });

    controller = usePlugin(AccountReportController);

    searchBarInputRef = signal.ref();

    setup() {
        onMounted(() => {
            const query = this.props.initialQuery || this.controller.searchBarInput || "";
            this.searchBarInputRef().value = query;
            if (query) {
                this.search();
            }
        });
    }

    //------------------------------------------------------------------------------------------------------------------
    // Search
    //------------------------------------------------------------------------------------------------------------------
    async search() {
        this.controller.searchBarInput = this.searchBarInputRef().value.trim();

        // Since the search bar is loaded before the report data, we need to wait for it
        await this.controller.reportLoadingPromise;

        this.controller.setLineSearchMatch();
        this.controller.invalidateVisibleLines();  // This update search_match on the stored lines.
    }
}
