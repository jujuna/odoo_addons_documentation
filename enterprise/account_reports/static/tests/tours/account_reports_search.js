import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add('account_reports_search', {
    steps: () => [
        {
            content: "click search",
            trigger: '.o_searchview_input',
            run: 'click',
        },
        {
            content: 'insert text in the searchbar',
            trigger: '.o_searchview_input',
            run: "edit 40",
        },
        {
            content: "test if the product sale line is present and unfold it",
            trigger: '.line_name:contains("400000 Product Sales")',
            run: "click",
        },
        {
            content: "test if the invoice line is present",
            trigger: ".line_name:contains('INV/2017/00003')",
        },
        {
            content: "fold the product sale line",
            trigger: ".line_name:contains('400000 Product Sales')",
            run: "click",
        },
        {
            content: "insert text in the searchbar",
            trigger: ".o_searchview_input",
            run: "edit INV/2017/00003",
        },
        {
            content: "test if the product sale line is present",
            trigger: ".line_name:contains('400000 Product Sales')",
        },
        {
            content: "test no other lines are present",
            trigger: "tbody > tr[data-id=line]:not(.o_hidden):not(.empty):count(1)",
        },
        {
            content: "click search",
            trigger: '.o_searchview_input',
            run: 'click',
        },
        {
            content: 'insert text in the search bar',
            trigger: '.o_searchview_input',
            run: "edit Account",
        },
        {
            content: 'test if the receivable line is present',
            trigger: '.line_name:contains("121000 Accounts Receivable")',
        },
        {
            content: "test if the payable line is present",
            trigger: ".line_name:contains('211000 Accounts Payable')",
        },
        {
            content: "check that no other lines are present",
            trigger: "tbody > tr[data-id=line]:not(.o_hidden):not(.empty):count(2)",
        },
        {
            content: 'insert text in the search bar',
            trigger: '.o_searchview_input',
            run: "edit 121000 Accounts Receivable",
        },
        {
            content: "open date filter",
            trigger: ".filter_date .o-dropdown",
            run: "click",
        },
        {
            content: "go to previous month",
            trigger: ".date_filter_month .btn_previous_date",
            run: "click",
        },
        {
            content: "close date filter",
            trigger: ".filter_date .o-dropdown",
            run: "click",
        },
        {
            content: "wait for the June lines to be loaded",
            trigger: ".line_name:contains('121000 Accounts Receivable') ~ .line_cell:contains('2,000.00')",
        },
        {
            content: "check that no other lines are present",
            trigger: "tbody > tr[data-id=line]:not(.o_hidden):not(.empty):count(1)",
        },
        {
            content: "test if the receivable line is present and unfold it",
            trigger: ".line_name:contains('121000 Accounts Receivable')",
            run: "click",
        },
        {
            content: "test if the invoice line is present",
            trigger: ".line_name:contains('INV/2017/00002')",
        },
    ]
});
