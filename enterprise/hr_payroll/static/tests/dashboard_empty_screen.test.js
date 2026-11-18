import { expect, test } from "@odoo/hoot";
import { mockDate } from "@odoo/hoot-mock";
import { mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";

import { DashboardEmptyScreen } from "@hr_payroll/components/dashboard/dashboard_empty_screen/dashboard_empty_screen";

defineMailModels();

test("empty screen shows the closing date sent as a string", async () => {
    mockDate("2026-10-30 10:00:00");
    mockService("action", { doAction() {} });

    await mountWithCleanup(DashboardEmptyScreen, {
        props: {
            closingDatesData: [
                { schedule: "monthly", label: "payslip batch", closing_date: "2026-11-28" },
            ],
        },
    });

    expect("h2").toHaveText("All done 👏");
    expect("span").toHaveText(/^The next payslip batch is scheduled on\s+\S+/);
    expect("button[name='all_payslips']").toHaveText("All Payslips");
    expect("span").toHaveCount(1);
});

test("empty screen tolerates a closing date not set", async () => {
    mockDate("2026-10-30 10:00:00");
    mockService("action", { doAction() {} });

    await mountWithCleanup(DashboardEmptyScreen, {
        props: {
            closingDatesData: [
                { schedule: "monthly", label: "payslip batch", closing_date: false },
            ],
        },
    });

    expect("h2").toHaveText("All done 👏");
    expect("button[name='all_payslips']").toHaveText("All Payslips");
});
