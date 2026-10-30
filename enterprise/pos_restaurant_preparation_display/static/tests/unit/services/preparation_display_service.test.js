import { test, expect } from "@odoo/hoot";
import { definePosPrepDisplayModels } from "@pos_enterprise/../tests/unit/data/generate_model_definitions";
import { setupPosPrepDisplayEnv } from "@pos_enterprise/../tests/unit/utils";
import { createPrepTicketWithCourses } from "@pos_restaurant_preparation_display/../tests/unit/utils";

definePosPrepDisplayModels();

test("filteredOrders with courses produces a separate order card", async () => {
    const store = await setupPosPrepDisplayEnv();
    await createPrepTicketWithCourses(store);
    const orders = store.filteredOrders;

    expect(orders.length).toBe(2);

    const keys = orders.map((o) => o._key);
    // All keys must be defined
    expect(keys.every((k) => k !== undefined && k !== null)).toBe(true);
});
