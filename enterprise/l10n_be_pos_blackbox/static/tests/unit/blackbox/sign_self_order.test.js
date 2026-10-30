import { test, expect, describe } from "@odoo/hoot";
import { setupPosBlackboxEnv } from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { SELF_ORDERING_INSZ_NUMBER } from "@l10n_be_pos_blackbox/common/blackbox/blackbox";

definePosModels();

describe("sign_self_order", () => {
    test("signed with the INSZ number reserved for self-ordering", async () => {
        const signSaleInputs = [];
        const expectRequest = async (mockRequest) => {
            const body = await mockRequest.json();
            if (body.operationName === "M110_signSale") {
                signSaleInputs.push(body.variables.data);
            }
            return {};
        };

        const store = await setupPosBlackboxEnv(expectRequest);
        const order = await getFilledOrder(store, {}, true);
        // The self-order is fetched from the server, the PoS only signs what it gets back
        patchWithCleanup(store.data, { callRelated: async () => ({ "pos.order": [order] }) });

        await store.getSelfOrderToSign(order.id);

        expect(signSaleInputs).toHaveLength(1);
        expect(signSaleInputs[0].employeeId).toBe(SELF_ORDERING_INSZ_NUMBER);
    });
});
