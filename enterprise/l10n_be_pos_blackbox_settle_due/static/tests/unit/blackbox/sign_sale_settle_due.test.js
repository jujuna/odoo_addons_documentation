import { test, expect, describe } from "@odoo/hoot";
import {
    expectTransactionLine,
    setupPosBlackboxEnv,
    expectGeneralProperties,
    expectCostCenter,
    expectFinancial,
    generatePosOrder,
} from "@l10n_be_pos_blackbox/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { mountPosApp, sendBufferKeys } from "@point_of_sale/../tests/unit/ui_utils";
import { contains, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { PosBlackboxBe } from "@l10n_be_pos_blackbox/common/blackbox/blackbox";

definePosModels();

describe("sign_sale with customer account", () => {
    patchWithCleanup(PosBlackboxBe.prototype, {
        async ping() {
            return true;
        },
    });

    const SETTLE_PRODUCT = {
        id: "dummy_product_for_settle_stuff_variant",
        name: "Dummy Product for Settle Invoice",
    };

    const setupSignSaleRecorder = async () => {
        const signSaleInputs = [];
        const store = await setupPosBlackboxEnv(async (request) => {
            const body = await request.json();
            if (body.operationName === "M110_signSale") {
                signSaleInputs.push(body.variables.data);
            }
            return {};
        });
        store.config.module_pos_restaurant = false;
        return { store, signSaleInputs };
    };

    test("signSale paying with customer account", async () => {
        const store = await setupPosBlackboxEnv();
        const models = store.models;
        const martini = models["product.product"].find((p) => p.name === "Dry Martini");
        const burger = models["product.product"].find((p) => p.name === "Burger of the Chef");
        const order = generatePosOrder(models, [
            {
                product_id: martini.id,
                qty: 2,
                price_unit: martini.lst_price,
                tax_ids: martini.taxes_id.map((t) => t.id),
            },
            {
                product_id: burger.id,
                qty: 1,
                price_unit: burger.lst_price,
                tax_ids: burger.taxes_id.map((t) => t.id),
            },
        ]);
        const partner = models["res.partner"].get(8);
        const payLaterMethod = models["pos.payment.method"].get(3);

        order.setPartner(partner);

        // Pay order with customer account
        order.state = "paid";
        store.models["pos.payment"].create({
            amount: order.priceIncl,
            pos_order_id: order,
            payment_method_id: payLaterMethod,
        });
        store.addPendingOrder([order.id]);

        const response = await store.blackbox.signSale.sign(order, "1234567890");
        const input = response.formatted;
        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        expectGeneralProperties(input, { order: order, ticketMedium: "DIGITAL" });

        expect(transactions).toHaveLength(2);
        expect(financials).toHaveLength(1);

        expectCostCenter(
            input.costCenter,
            partner.id.toString() + " " + partner.name,
            "CUSTOMER",
            partner.vat
        );

        expectFinancial(
            financials[0],
            payLaterMethod.name,
            "PAYMENT",
            order.priceIncl,
            "CUSTOMER_CREDIT"
        );
    });

    test("signSale depositing money", async () => {
        const { store, signSaleInputs } = await setupSignSaleRecorder();
        const partner = store.models["res.partner"].get(8);
        partner.vat = "BE0246697724";
        partner.name = "Test Customer";

        await store.onClickDepositMoney(0, partner.id, partner.id);
        const order = store.getOrder();
        await mountPosApp(store);
        // Type "30" on the payment screen numpad, as a cashier would.
        await sendBufferKeys("3", "0");
        expect(order.payment_ids).toHaveLength(1);
        expect(order.payment_ids[0].amount).toBe(30);

        await contains(".payment-screen .validation-button.highlight").click();
        // Confirm the "Do you want to deposit ...?" dialog.
        await contains(".modal .btn-primary").click();

        expect(signSaleInputs).toHaveLength(1);

        const input = signSaleInputs[0];
        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        expectGeneralProperties(input, { ticketMedium: "PAPER", employeeId: "97121722222" });
        expectCostCenter(
            input.costCenter,
            partner.id.toString() + " " + partner.name,
            "CUSTOMER",
            partner.vat
        );

        expect(transactions).toHaveLength(1);
        expectTransactionLine(
            transactions[0],
            SETTLE_PRODUCT,
            1,
            "PIECE",
            30,
            "X",
            "SINGLE_PRODUCT"
        );
        expect(input.transaction.transactionTotal).toBe(30);

        expect(financials).toHaveLength(1);
        expectFinancial(financials[0], "Bank", "PAYMENT", 30, "CARD_UNKNOWN");
        expect(financials.some((f) => f.name === "Change")).toBe(false);
    });

    test("signSale settling invoices", async () => {
        const { store, signSaleInputs } = await setupSignSaleRecorder();
        const partner = store.models["res.partner"].get(8);
        partner.vat = "BE0246697724";
        partner.name = "Test Customer";

        const originalRead = store.data.read.bind(store.data);
        patchWithCleanup(store.data, {
            read: async (model, ids, fields, ...rest) => {
                if (model === "account.move") {
                    return [
                        { id: 1, move_type: "out_invoice", amount_residual: 60 },
                        { id: 2, move_type: "out_invoice", amount_residual: 40 },
                    ];
                }
                return originalRead(model, ids, fields, ...rest);
            },
        });

        // Settling invoices creates one settle line per invoice, already carrying
        // the residual amount, and the cashier pays the exact total.
        await store.onClickSettleInvoices([1, 2], partner.id, partner.id);
        await mountPosApp(store);
        await contains(`.paymentmethod:contains("Cash")`).click();
        await contains(".payment-screen .validation-button.highlight").click();

        expect(signSaleInputs).toHaveLength(1);

        const input = signSaleInputs[0];
        const transactions = input.transaction.transactionLines;
        const financials = input.financials;

        expectGeneralProperties(input, { ticketMedium: "PAPER", employeeId: "97121722222" });
        expectCostCenter(
            input.costCenter,
            partner.id.toString() + " " + partner.name,
            "CUSTOMER",
            partner.vat
        );

        expect(transactions).toHaveLength(2);
        expectTransactionLine(
            transactions[0],
            SETTLE_PRODUCT,
            1,
            "PIECE",
            60,
            "X",
            "SINGLE_PRODUCT"
        );
        expectTransactionLine(
            transactions[1],
            SETTLE_PRODUCT,
            1,
            "PIECE",
            40,
            "X",
            "SINGLE_PRODUCT"
        );
        expect(input.transaction.transactionTotal).toBe(100);

        expect(financials).toHaveLength(1);
        expectFinancial(financials[0], "Cash", "PAYMENT", 100, "CASH");
        expect(financials.some((f) => f.name === "Change")).toBe(false);
    });

    test("a settlement is signed as a sale, never as an empty/cancelled receipt", async () => {
        const { store } = await setupSignSaleRecorder();
        const partner = store.models["res.partner"].get(8);

        let signSaleCount = 0;
        let signEmptyCount = 0;
        patchWithCleanup(store.blackbox.signSale, {
            async sign() {
                signSaleCount++;
                return { formatted: {} };
            },
            async signEmptyOrder() {
                signEmptyCount++;
                return { formatted: {} };
            },
        });

        const originalRead = store.data.read.bind(store.data);
        patchWithCleanup(store.data, {
            read: async (model, ids, fields, ...rest) => {
                if (model === "account.move") {
                    return [{ id: 1, move_type: "out_invoice", amount_residual: 100 }];
                }
                return originalRead(model, ids, fields, ...rest);
            },
        });

        await store.onClickSettleInvoices([1], partner.id, partner.id);
        const orderUuid = store.getOrder().uuid;
        await mountPosApp(store);
        await contains(`.paymentmethod:contains("Cash")`).click();
        await contains(".payment-screen .validation-button.highlight").click();

        expect(signSaleCount).toBe(1);
        expect(signEmptyCount).toBe(0);
        expect(store.models["pos.order"].getBy("uuid", orderUuid)).toBe(undefined);
    });
});
