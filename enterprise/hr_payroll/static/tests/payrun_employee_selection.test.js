import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mockService, mountView } from "@web/../tests/web_test_helpers";
import { defineHrPayrollModels } from "@hr_payroll/../tests/hr_payroll_test_helpers";
import { PayrollAvatarCard } from "@hr_payroll/core/web/avatar_card/payroll_avatar_card";

describe.current.tags("desktop");
defineHrPayrollModels();

test("employee selection of the pay run flow never opens the employee form", async () => {
    mockService("action", {
        doAction(action) {
            expect.step(`doAction ${action.res_model || action}`);
        },
    });
    mockService("popover", {
        add(target, component, props, options) {
            expect(component).toBe(PayrollAvatarCard);
            expect.step(`avatar card ${props.model} ${props.id} on ${target.getAttribute("name")}`);
            return () => {
                expect.step("avatar card closed");
                options.onClose();
            };
        },
    });
    await mountView({
        type: "list",
        resModel: "hr.employee",
        domain: [["id", "=", 100]],
        arch: `
            <list js_class="hr_version_payrun_list">
                <field name="name"/>
                <field name="work_email"/>
            </list>
        `,
    });

    // the name opens the avatar card, a second click closes it
    await click(".o_data_row td[name='name']");
    await animationFrame();
    await click(".o_data_row td[name='name']");
    await animationFrame();
    expect.verifySteps(["avatar card hr.employee 100 on name", "avatar card closed"]);

    // the other cells (un)select the employee
    await click(".o_data_row td[name='work_email']");
    await animationFrame();
    expect(queryAll(".o_data_row .o_list_record_selector input:checked")).toHaveLength(1);
    await click(".o_data_row td[name='work_email']");
    await animationFrame();
    expect(queryAll(".o_data_row .o_list_record_selector input:checked")).toHaveLength(0);

    expect.verifySteps([]);
});
