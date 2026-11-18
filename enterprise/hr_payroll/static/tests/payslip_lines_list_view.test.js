import { test, expect } from "@odoo/hoot";
import { click, edit } from "@odoo/hoot-dom";
import { mountView } from "@web/../tests/web_test_helpers";
import { defineHrPayrollModels } from "@hr_payroll/../tests/hr_payroll_test_helpers";
import { HrPayslip } from "@hr_payroll/../tests/mock_server/mock_models/hr_payslip";
import { HrPayslipLine } from "@hr_payroll/../tests/mock_server/mock_models/hr_payslip_line";
import { HrSalaryRule } from "@hr_payroll/../tests/mock_server/mock_models/hr_salary_rule";
import { payslipShowAllState } from "../src/views/payslip_form/hr_payslip_list_row_visibility_renderer";
import { animationFrame } from "@odoo/hoot-mock";

defineHrPayrollModels();

test("default value cells switch from empty to muted when toggling show all", async () => {
    HrPayslipLine._records.push(
        { id: 1, quantity: 1.0, rate: 100.0, amount: 100.0, total: 100.0, slip_id: 1, appears_on_payslip: "always", name: "1) default values, always appears" },
        { id: 2, quantity: 2.0, rate: 50.0, amount: 80.0, total: 100.0, slip_id: 1, appears_on_payslip: "always", name: "2) non default values, always appears" },
        { id: 3, quantity: 1.0, rate: 100.0, amount: 100.0, total: 100.0, slip_id: 1, appears_on_payslip: "non_zero", name: "3) non zero total, non zero appears" },
        { id: 4, quantity: 1.0, rate: 100.0, amount: 100.0, total: 0.0, slip_id: 1, appears_on_payslip: "non_zero", name: "4) zero total, non zero appears" },
        { id: 5, quantity: 1.0, rate: 100.0, amount: 100.0, total: 100.0, slip_id: 1, appears_on_payslip: "never", name: "5) default values, never appears" },
    )
    HrPayslip._records.push(
        {
            id: 1,
            line_ids: [1, 2, 3, 4, 5],
        },
    )
    payslipShowAllState.showAll = false;

    await mountView({
        type: "form",
        resModel: "hr.payslip",
        resId: 1,
        arch: `
            <form>
                <field name="line_ids" widget="payslip_lines_2many">
                    <list editable="bottom">
                        <field name="name"/>
                        <field name="quantity" is_default_value="quantity == 1.0"/>
                        <field name="rate" is_default_value="rate == 100.0"/>
                        <field name="amount" is_default_value="amount == total"/>
                        <field name="total"/>
                        <field name="appears_on_payslip" column_invisible="1"/>
                    </list>
                </field>
            </form>
        `,
    });

    var all_lines = [...document.querySelectorAll('tr')];
    var default_always = all_lines.find(tr => tr.textContent.includes('1) default values, always appears'));
    var non_default_always = all_lines.find(tr => tr.textContent.includes('2) non default values, always appears'));
    var non_zero_non_zero = all_lines.find(tr => tr.textContent.includes('3) non zero total, non zero appears'));
    var zero_non_zero = all_lines.find(tr => tr.textContent.includes('4) zero total, non zero appears'));
    var default_never = all_lines.find(tr => tr.textContent.includes( '5) default values, never appears'));

    expect(default_always).toHaveCount(1);
    expect(non_default_always).toHaveCount(1);
    expect(non_zero_non_zero).toHaveCount(1);
    expect(zero_non_zero).toBe(undefined);
    expect(default_never).toBe(undefined);

    const field_names = ['quantity', 'rate', 'amount'];
    for (const field of field_names) {

        var default_always_cell = default_always.querySelector(`td[name="${field}"]`);
        var non_default_always_cell = non_default_always.querySelector(`td[name="${field}"]`);
        expect(default_always_cell.classList.contains("invisible")).toBe(false);
        expect(default_always_cell.textContent).toBe("");
        expect(default_always_cell.classList.contains("text-muted")).toBe(false);
        expect(non_default_always_cell.classList.contains("invisible")).toBe(false);
        expect(non_default_always_cell.classList.contains("text-muted")).toBe(false);
    }

    payslipShowAllState.showAll = true;
    await animationFrame();

    var all_lines = [...document.querySelectorAll('tr')];
    var default_always = all_lines.find(tr => tr.textContent.includes('1) default values, always appears'));
    var non_default_always = all_lines.find(tr => tr.textContent.includes('2) non default values, always appears'));
    var non_zero_non_zero = all_lines.find(tr => tr.textContent.includes('3) non zero total, non zero appears'));
    var zero_non_zero = all_lines.find(tr => tr.textContent.includes('4) zero total, non zero appears'));
    var default_never = all_lines.find(tr => tr.textContent.includes( '5) default values, never appears'));

    expect(default_always).toHaveCount(1);
    expect(non_default_always).toHaveCount(1);
    expect(non_zero_non_zero).toHaveCount(1);
    expect(zero_non_zero).toHaveCount(1);
    expect(default_never).toHaveCount(1);

    for (const field of field_names) {

        var default_always_cell = default_always.querySelector(`td[name="${field}"]`);
        var non_default_always_cell = non_default_always.querySelector(`td[name="${field}"]`);

        expect(default_always_cell.classList.contains("invisible")).toBe(false);
        expect(default_always_cell.classList.contains("text-muted")).toBe(true);
        expect(non_default_always_cell.classList.contains("invisible")).toBe(false);
        expect(non_default_always_cell.classList.contains("text-muted")).toBe(false);
    }

    for (const field of field_names) {
        var default_always_cell = default_always.querySelector(`td[name="${field}"]`);

        await click(default_always_cell);
        await animationFrame();

        const input = default_always_cell.querySelector("input");
        expect(input).not.toBe(null);

        await edit("7");
        await animationFrame();

        await click(non_default_always.querySelector(`td[name="name"]`));
        await animationFrame();

        expect(default_always_cell.textContent).toBe("7.00");
        expect(default_always_cell.classList.contains("text-muted")).toBe(false);
    }
});

test("the style of the salary rule applies on the row, without a rule column", async () => {
    HrSalaryRule._records.push(
        { id: 1, name: "Bold rule", bold: true, italic: true },
        { id: 2, name: "Plain rule" },
    );
    HrPayslipLine._records.push(
        { id: 1, quantity: 2.0, total: 80.0, slip_id: 1, salary_rule_id: 1, appears_on_payslip: "always", name: "Bold line" },
        { id: 2, quantity: 2.0, total: 80.0, slip_id: 1, salary_rule_id: 2, appears_on_payslip: "always", name: "Plain line" },
    );
    HrPayslip._records.push({ id: 1, line_ids: [1, 2] });
    payslipShowAllState.showAll = true;

    await mountView({
        type: "form",
        resModel: "hr.payslip",
        resId: 1,
        arch: `
            <form>
                <field name="line_ids" widget="payslip_lines_2many">
                    <list editable="bottom" create="0">
                        <field name="name"/>
                        <field name="salary_rule_id" widget="salary_rule_style" readonly="1"/>
                        <field name="quantity"/>
                        <field name="total"/>
                        <field name="appears_on_payslip" column_invisible="1"/>
                    </list>
                </field>
            </form>
        `,
    });

    const allLines = [...document.querySelectorAll("tr")];
    const boldLine = allLines.find((tr) => tr.textContent.includes("Bold line"));
    const plainLine = allLines.find((tr) => tr.textContent.includes("Plain line"));
    expect(boldLine.classList.contains("fw-bold")).toBe(true);
    expect(boldLine.classList.contains("fst-italic")).toBe(true);
    expect(plainLine.classList.contains("fw-bold")).toBe(false);
    // the rule is only loaded for its style, it has no column
    expect(document.querySelector('th[data-name="salary_rule_id"]')).toBe(null);
    expect(boldLine.querySelector('td[name="salary_rule_id"]')).toBe(null);
});

test("title rows keep their cells but only show the name", async () => {
    HrSalaryRule._records.push(
        { id: 1, name: "Title rule", title: true },
        { id: 2, name: "Regular rule", title: false },
    );
    HrPayslipLine._records.push(
        { id: 1, quantity: 2.0, total: 80.0, slip_id: 1, salary_rule_id: 1, appears_on_payslip: "always", name: "Title line" },
        { id: 2, quantity: 2.0, total: 80.0, slip_id: 1, salary_rule_id: 2, appears_on_payslip: "always", name: "Regular line" },
    );
    HrPayslip._records.push({ id: 1, line_ids: [1, 2] });
    payslipShowAllState.showAll = true;

    await mountView({
        type: "form",
        resModel: "hr.payslip",
        resId: 1,
        arch: `
            <form>
                <field name="line_ids" widget="payslip_lines_2many">
                    <list editable="bottom" create="0">
                        <field name="name"/>
                        <field name="salary_rule_id" widget="salary_rule_style" readonly="1"/>
                        <field name="quantity"/>
                        <field name="total"/>
                        <field name="appears_on_payslip" column_invisible="1"/>
                    </list>
                </field>
            </form>
        `,
    });

    const allLines = [...document.querySelectorAll("tr")];
    const titleLine = allLines.find((tr) => tr.textContent.includes("Title line"));
    const regularLine = allLines.find((tr) => tr.textContent.includes("Regular line"));
    expect(titleLine.querySelector('td[name="name"]').textContent).toBe("Title line");
    for (const field of ["quantity", "total"]) {
        // the cell is kept (and colored on hover), only its value is left out
        const titleCell = titleLine.querySelector(`td[name="${field}"]`);
        expect(titleCell).not.toBe(null);
        expect(titleCell.classList.contains("invisible")).toBe(false);
        expect(titleCell.textContent).toBe("");
        expect(regularLine.querySelector(`td[name="${field}"]`).textContent).not.toBe("");
    }
});
