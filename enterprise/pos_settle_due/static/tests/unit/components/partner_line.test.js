import { animationFrame, expect, queryOne, test } from "@odoo/hoot";
import { setupAndMountPosApp } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import * as utils from "@point_of_sale/../tests/unit/ui_utils";

definePosModels();

test.tags("mobile");
test("partner balance status", async () => {
    const store = await setupAndMountPosApp();
    const partner = store.models["res.partner"].get(5);
    partner.total_due = 150;
    await utils.clickPartnerButton();
    // with outstanding balance.
    const partnerDue = queryOne(".partner-info:contains(User on budget) .partner-due");
    expect(partnerDue).toHaveText("Due: $ 150.00");
    expect(partnerDue).toHaveClass("border-danger");
    // credit balance (deposit).
    partner.total_due = -21;
    await animationFrame();
    expect(partnerDue).toHaveText("Deposit: $ 21.00");
    expect(partnerDue).toHaveClass("border-success");
});
