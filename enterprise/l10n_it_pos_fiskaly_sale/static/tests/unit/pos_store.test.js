import { test, expect, describe } from "@odoo/hoot";
import { setupPosEnv, createTestProduct } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

definePosModels();
describe("l10n_it_pos_fiskaly_sale", () => {
    test("the down payment product is never asked for an exemption", async () => {
        const store = await setupPosEnv();
        store.config.l10n_it_fiskaly_system_id = "system";
        const product = createTestProduct(store, { name: "Down Payment", taxes_id: [] });
        store.config.down_payment_product_id = { product_tmpl_id: { id: product.id } };
        const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: product });
        expect(exemption).toBe(null);
    });
});
