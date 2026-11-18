import { test, expect, mockFetch } from "@odoo/hoot";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import "@l10n_de_pos_cert/app/models/pos_order";
import "@l10n_de_pos_cert/app/services/pos_store";

definePosModels();

const setupFiskalyRetail = async () => {
    const store = await setupPosEnv();
    store.config.module_pos_restaurant = false;
    store.config.is_company_country_germany = true;
    store.config.l10n_de_fiskaly_tss_id = "tss-id|client-id";
    const fiskalyCalls = [];
    store.transactionCall = async (payload, data) => {
        fiskalyCalls.push(data.state);
        return {};
    };
    const syncedTxUuids = [];
    const originalCall = store.data.call.bind(store.data);
    store.data.call = async (model, method, args, kwargs) => {
        if (model === "pos.order" && method === "sync_from_ui") {
            syncedTxUuids.push(args[0][0].l10n_de_fiskaly_transaction_uuid);
        }
        return originalCall(model, method, args, kwargs);
    };
    return { store, fiskalyCalls, syncedTxUuids };
};

const setupFiskalyStore = async () => {
    const store = await setupPosEnv();
    store.config.is_company_country_germany = true;
    store.config.l10n_de_fiskaly_tss_id = "tss-id|client-id";
    store.apiUrl = "https://fiskaly.test/api/v2";
    store.setApiToken("test-token");

    const order = await getFilledOrder(store);
    order.l10n_de_fiskaly_transaction_uuid = "tx-uuid";
    return { store, order };
};

test("saved draft order can be deleted in DE Fiskaly retail flow", async () => {
    const { store, fiskalyCalls, syncedTxUuids } = await setupFiskalyRetail();
    const order = store.addNewOrder();
    await store.addLineToCurrentOrder({ product_tmpl_id: store.models["product.template"].get(5) });
    const txUuid = order.l10n_de_fiskaly_transaction_uuid;
    expect(order.isReceiptStarted).toBe(true);
    await store.syncAllOrders({ orders: [order] });
    expect(order.isSynced).toBe(true);

    expect(await store.deleteOrders([order])).toBe(true);
    expect(fiskalyCalls).toEqual(["ACTIVE", "CANCELLED"]);
    expect(syncedTxUuids.at(-1)).toBe(txUuid);
    expect(store.models["pos.order"].get(order.id)).toBeEmpty();
});

test("cancelled receipt is restarted when a product is added again", async () => {
    const { store, fiskalyCalls } = await setupFiskalyRetail();
    const order = store.addNewOrder();
    const product = store.models["product.template"].get(5);
    await store.addLineToCurrentOrder({ product_tmpl_id: product });
    const firstTxUuid = order.l10n_de_fiskaly_transaction_uuid;
    order.removeOrderline(order.lines[0]);
    await store.handleFiskalyCancellation(order);
    expect(order.isReceiptCancelled).toBe(true);

    await store.addLineToCurrentOrder({ product_tmpl_id: product });
    expect(fiskalyCalls).toEqual(["ACTIVE", "CANCELLED", "ACTIVE"]);
    expect(order.isReceiptStarted).toBe(true);
    expect(order.l10n_de_fiskaly_transaction_uuid).not.toBe(firstTxUuid);
});

test("paid order still waits for its receipt transaction in DE Fiskaly flow", async () => {
    const { store } = await setupFiskalyRetail();
    const order = await getFilledOrder(store);
    order.state = "paid";
    store.createTransaction = async () => {
        throw new Error("fiskaly down");
    };

    await expect(store.syncAllOrders({ orders: [order] })).rejects.toThrow("fiskaly down");
    expect(order.isSynced).toBe(false);
});

test("finalizeReceiptTransaction recovers from a lost response (E_TX_UPSERT, transaction already FINISHED)", async () => {
    const { store, order } = await setupFiskalyStore();

    let putCallCount = 0;
    mockFetch((input, init) => {
        if (init.method === "GET") {
            return { revision: 2, state: "FINISHED" };
        }
        putCallCount++;
        return new Response(JSON.stringify({ code: "E_TX_UPSERT", status_code: 400 }), {
            status: 400,
        });
    });

    const result = await store.finalizeReceiptTransaction(order, "FINISHED");

    expect(result).toEqual({ revision: 2, state: "FINISHED" });
    expect(putCallCount).toBe(1);
    expect(order.uiState.tx_revision).toBe(3);
});

test("finalizeReceiptTransaction retries with the corrected revision when the transaction is still open elsewhere", async () => {
    const { store, order } = await setupFiskalyStore();

    let putCallCount = 0;
    mockFetch((input, init) => {
        const url = typeof input === "string" ? input : input.url;
        if (init.method === "GET") {
            return { revision: 4, state: "ACTIVE" };
        }
        putCallCount++;
        if (url.includes("tx_revision=2")) {
            return new Response(JSON.stringify({ code: "E_TX_UPSERT", status_code: 400 }), {
                status: 400,
            });
        }
        return { revision: 5, state: "FINISHED" };
    });

    const result = await store.finalizeReceiptTransaction(order, "FINISHED");

    expect(result).toEqual({ revision: 5, state: "FINISHED" });
    expect(putCallCount).toBe(2);
});

test("only the orders Fiskaly signed are synced", async () => {
    const { store } = await setupFiskalyRetail();
    const failingOrder = await getFilledOrder(store);
    const nextOrder = await getFilledOrder(store);
    for (const order of [failingOrder, nextOrder]) {
        order.receiptStarted();
        order.state = "paid";
    }
    store.finishShortTransaction = async (order) => {
        if (order === failingOrder) {
            throw new Error("fiskaly rejected the receipt");
        }
        order.receiptFinished();
    };

    await expect(store.syncAllOrders({ orders: [failingOrder, nextOrder] })).rejects.toThrow(
        "fiskaly rejected the receipt"
    );
    expect(failingOrder.isSynced).toBe(false);
    expect(nextOrder.isSynced).toBe(true);
});

test("receipt cancelled on Fiskaly is signed in a new transaction when paid", async () => {
    const store = await setupPosEnv();
    store.config.module_pos_restaurant = false;
    store.config.is_company_country_germany = true;
    store.config.l10n_de_fiskaly_tss_id = "tss-id|client-id";
    store.apiUrl = "https://kassensichv.test/api/v2";
    store.setApiToken("token");
    const order = await getFilledOrder(store);
    // Receipt started on a previous day, then cancelled by cancelActiveTransactions at closing
    order.l10n_de_fiskaly_transaction_uuid = "cancelled-tx";
    order.receiptStarted();
    order.state = "paid";

    const requests = [];
    const fetchFn = window.fetch;
    patchWithCleanup(window, {
        fetch(url, init = {}) {
            const match = String(url).match(/\/tx\/([^?]+)(?:\?tx_revision=(\d))?$/);
            if (!match) {
                return fetchFn(url, init);
            }
            const [, txId, revision] = match;
            const state = init.method === "PUT" ? JSON.parse(init.body).state : "GET";
            requests.push(txId === "cancelled-tx" ? `${state} cancelled-tx` : state);
            let status = 200;
            let body = {};
            if (txId === "cancelled-tx") {
                if (init.method === "GET") {
                    body = { _id: txId, state: "CANCELLED", revision: 2 };
                } else {
                    status = 400;
                    body = { status_code: 400, code: "E_TX_UPSERT" };
                }
            } else if (revision === "2") {
                body = {
                    _id: txId,
                    state: "FINISHED",
                    number: 42,
                    time_start: 1760000000,
                    time_end: 1760000060,
                    tss_serial_number: "tss-serial",
                    client_serial_number: "client-serial",
                    log: { timestamp_format: "unixTime" },
                    signature: { value: "sig", algorithm: "ecdsa", public_key: "key" },
                };
            }
            return new Response(JSON.stringify(body), {
                status,
                headers: { "Content-Type": "application/json" },
            });
        },
    });

    await store.syncAllOrders({ orders: [order] });
    expect(requests).toEqual(["FINISHED cancelled-tx", "GET cancelled-tx", "ACTIVE", "FINISHED"]);
    expect(order.l10n_de_fiskaly_transaction_uuid).not.toBe("cancelled-tx");
    expect(order.l10n_de_fiskaly_transaction_number).toBe(42);
    expect(order.isSynced).toBe(true);
});

const getFilledRefund = async (store) => {
    const order = store.addNewOrder();
    order.is_refund = true;
    for (const [templateId, qty] of [
        [5, -3],
        [6, -2],
    ]) {
        await store.addLineToOrder(
            { product_tmpl_id: store.models["product.template"].get(templateId), qty },
            order
        );
    }
    return order;
};

test("refund amounts per VAT rate keep the sign of the order total", async () => {
    const { store } = await setupFiskalyRetail();
    for (const isRefund of [false, true]) {
        const order = isRefund ? await getFilledRefund(store) : await getFilledOrder(store);
        const taxedAmounts = store
            ._createAmountPerVatRateArray(order)
            .filter((entry) => entry.vat_rate !== "0")
            .map((entry) => parseFloat(entry.amount));
        expect(taxedAmounts).toEqual(isRefund ? [-10.35, -7.5] : [10.35, 7.5]);
        expect(order.priceIncl).toBeCloseTo(isRefund ? -17.85 : 17.85);
    }
});
