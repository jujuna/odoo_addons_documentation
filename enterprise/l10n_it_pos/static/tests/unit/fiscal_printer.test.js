import { expect, getFixture, test } from "@odoo/hoot";
import { onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

definePosModels();

const FPMATE_RESPONSE = `<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body><response success="true" code="" status="2"><addInfo><elementList>fiscalReceiptNumber,fiscalReceiptDate,zRepNumber</elementList><fiscalReceiptNumber>7</fiscalReceiptNumber><fiscalReceiptDate>2/10/2026</fiscalReceiptDate><zRepNumber>3</zRepNumber></addInfo></response></soapenv:Body></soapenv:Envelope>`;

const setupFiscalPrinter = async ({ withImagePrinter = false } = {}) => {
    const container = document.createElement("div");
    container.id = "receipt-iframe-container";
    getFixture().append(container);

    const store = await setupPosEnv();
    const italy = store.models["res.country"].create({ id: 1000, name: "Italy", code: "IT" });
    store.config.company_id.update({ country_id: italy });

    const fiscalPrinter = store.models["pos.printer"].create({
        name: "RT",
        printer_type: "it_fiscal_printer",
        use_lna: false,
    });
    // printer_ip is not part of the mocked pos.printer fields
    fiscalPrinter.printer_ip = "printer1.epson.local";
    fiscalPrinter._instance = await store.ticketPrinter.createPrinterInstance(fiscalPrinter);
    const imagePrinter = store.models["pos.printer"].create({
        name: "Epson",
        printer_type: "epson_epos",
    });
    imagePrinter._instance = await store.ticketPrinter.createPrinterInstance(imagePrinter);
    store.config.update({
        receipt_printer_ids: withImagePrinter ? [fiscalPrinter, imagePrinter] : [fiscalPrinter],
    });
    store.ticketPrinter.defaultPrinter = fiscalPrinter;

    onRpc("https://printer1.epson.local/cgi-bin/fpmate.cgi", async (request) => {
        const body = await request.text();
        expect.step(body.includes("printerFiscalReceipt") ? "fiscal receipt" : "fpmate");
        return new Response(FPMATE_RESPONSE, { status: 200 });
    });
    onRpc("report.point_of_sale.report_saledetails", "get_sale_details", () => ({
        currency: { total_paid: 0 },
        payments: [],
        taxes: [],
        products: [],
        refund_products: [],
        cancelled_products: [],
        session_state: "opened",
    }));
    for (const paymentMethod of store.models["pos.payment.method"].getAll()) {
        paymentMethod.it_payment_code = "0";
    }
    patchWithCleanup(store.ticketPrinter, {
        // The receipt QWeb views are served by the server, not available in hoot.
        async generateIframe() {
            const iframe = document.createElement("iframe");
            iframe.srcdoc = '<html id="pos-receipt"><head></head><body>Receipt</body></html>';
            container.replaceChildren(iframe);
            await new Promise((resolve) => (iframe.onload = resolve));
            return iframe;
        },
        async generateImage() {
            return "image";
        },
        _print() {
            expect.step("web print");
        },
    });
    patchWithCleanup(imagePrinter._instance, {
        async print() {
            expect.step("image printer");
            return { successful: true };
        },
    });
    return store;
};

test("fiscal printer: the sale details report falls back to the browser print", async () => {
    const store = await setupFiscalPrinter();
    expect(store.config.useFiscalPrinter).toBe(true);

    await store.ticketPrinter.printSaleDetailsReceipt();
    expect.verifySteps(["web print"]);
});

test("fiscal printer: the cash move receipt falls back to the browser print", async () => {
    const store = await setupFiscalPrinter();

    await store.ticketPrinter.printCashMoveReceipt({
        reason: "Change",
        translatedType: "out",
        order: store.addNewOrder(),
        formattedAmount: "10.00",
    });
    expect.verifySteps(["web print"]);
});

test("fiscal printer: the sale details report goes to the other receipt printer", async () => {
    const store = await setupFiscalPrinter({ withImagePrinter: true });

    const result = await store.ticketPrinter.printSaleDetailsReceipt();
    expect(result.successful).toBe(true);
    expect.verifySteps(["image printer"]);
});

test("fiscal printer: a paid order is sent to the fiscal printer", async () => {
    const store = await setupFiscalPrinter();
    const order = await getFilledOrder(store);
    const validation = new OrderPaymentValidation({
        pos: store,
        orderUuid: order.uuid,
        fastPaymentMethod: order.config.fast_payment_method_ids[0],
    });
    await validation.validateOrder(false);
    // the cash drawer is opened once the fiscal receipt is printed
    await expect.waitForSteps(["fiscal receipt", "fpmate"]);
});
