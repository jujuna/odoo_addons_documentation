import { test, expect } from "@odoo/hoot";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

definePosModels();

test("isCustomerRequired", async () => {
    const posStore = await setupPosEnv();
    const order = await getFilledOrder(posStore);
    // partner is required for EC company
    expect(order.isCustomerRequired).toBe(true);
    const existingPartner = posStore.models["res.partner"].get(3);
    order.partner_id = existingPartner;
    expect(order.isCustomerRequired).toBe(false);
});
