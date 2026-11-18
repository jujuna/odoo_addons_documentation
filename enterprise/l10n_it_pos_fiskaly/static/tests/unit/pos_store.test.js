import { test, expect, describe } from "@odoo/hoot";
import {
    setupPosEnv,
    createTestProduct,
    createComboTemplate,
    createComboItemProduct,
} from "@point_of_sale/../tests/unit/utils";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { ComboConfiguratorPopup } from "@point_of_sale/app/components/popups/combo_configurator_popup/combo_configurator_popup";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

definePosModels();
describe("l10n_it_pos_fiskaly", () => {
    const setupFiskalyStore = async () => {
        const store = await setupPosEnv();
        store.config.l10n_it_fiskaly_system_id = "system";
        return store;
    };

    const createTax = (store, values) =>
        store.models["account.tax"].create({
            id: values.id,
            name: values.name,
            amount: values.amount,
            amount_type: "percent",
            price_include: true,
            l10n_it_exempt_reason: values.l10n_it_exempt_reason || false,
        });

    test("an allowed rate is added without asking for an exemption", async () => {
        const store = await setupFiskalyStore();
        const tax = createTax(store, { id: 9001, name: "IT 22%", amount: 22 });
        const product = createTestProduct(store, { name: "Taxed", taxes_id: [tax] });
        const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: product });
        expect(exemption).toBe(null);
    });

    test("an unmapped rate is refused", async () => {
        const store = await setupFiskalyStore();
        const tax = createTax(store, { id: 9002, name: "IT 7%", amount: 7 });
        const product = createTestProduct(store, { name: "Odd rate", taxes_id: [tax] });
        const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: product });
        expect(exemption).toBe(false);
    });

    test("a zero rate resolves its exemption from the natura", async () => {
        const store = await setupFiskalyStore();
        const cases = [
            ["N1", "CAUSE_2"],
            ["N2.2", "NOT_SUBJECT"],
            ["N3.1", "NOT_TAXABLE"],
            ["N4", "CAUSE_1"],
            ["N5", "CAUSE_3"],
            ["N6.9", "CAUSE_4"],
            ["N7", "CAUSE_4"],
        ];
        let id = 9100;
        for (const [natura, code] of cases) {
            const tax = createTax(store, {
                id: id++,
                name: `IT ${natura}`,
                amount: 0,
                l10n_it_exempt_reason: natura,
            });
            const product = createTestProduct(store, { name: natura, taxes_id: [tax] });
            const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: product });
            expect(exemption).toBe(code);
        }
    });

    test("the tip product is always not subject", async () => {
        const store = await setupFiskalyStore();
        const product = createTestProduct(store, { name: "Tips", taxes_id: [] });
        store.config.tip_product_id = { product_tmpl_id: { id: product.id } };
        const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: product });
        expect(exemption).toBe("NOT_SUBJECT");
    });

    test("a tip added to the order is not subject and can be paid", async () => {
        const store = await setupFiskalyStore();
        const { template } = createTestProduct(store, {
            name: "Restaurant service",
            price: 48,
            taxes_id: [createTax(store, { id: 9600, name: "IT 22% service", amount: 22 })],
        });
        const { variant: tipProduct } = createTestProduct(store, {
            name: "Voluntary tip",
            taxes_id: [],
        });
        store.config.iface_tipproduct = true;
        store.config.tip_product_id = tipProduct;
        await store.addLineToCurrentOrder({ product_tmpl_id: template }, {}, false);
        const tipLine = await store.setTip(2);
        expect(tipLine.l10n_it_fiskaly_vat_exemption).toBe("NOT_SUBJECT");
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(0);
        expect(result.navigated).toBe(true);
    });

    test("a combo product is never asked for an exemption", async () => {
        const store = await setupFiskalyStore();
        const { variant } = createComboItemProduct(store, { name: "Combo item" });
        const { template } = createComboTemplate(store, {
            name: "Combo",
            combos: [{ name: "Main", items: [{ product: variant }] }],
        });
        const exemption = await store.l10nItFiskalyVatExemption({ product_tmpl_id: template });
        expect(exemption).toBe(null);
    });

    const createExemptCombo = (store) => {
        const tax = createTax(store, { id: 9400, name: "IT 0%", amount: 0 });
        const { variant } = createComboItemProduct(store, { name: "Exempt item" });
        variant.product_tmpl_id.taxes_id = [tax];
        const { template, combos } = createComboTemplate(store, {
            name: "Combo",
            combos: [{ name: "Main", items: [{ product: variant }] }],
        });
        const comboOpts = [
            {
                combo_item_id: combos[0].combo_item_ids[0],
                price_unit: 10,
                qty: 1,
                attribute_custom_values: {},
            },
        ];
        return { template, comboOpts };
    };

    test("the exemption chosen in the configurator is set on the combo child", async () => {
        const store = await setupFiskalyStore();
        const { template, comboOpts } = createExemptCombo(store);
        const comboItemId = comboOpts[0].combo_item_id.id;
        store.l10nItFiskalyComboExemptions[template.id] = { [comboItemId]: "CAUSE_1" };
        const line = await store.addLineToCurrentOrder(
            { product_tmpl_id: template },
            { comboOpts },
            false
        );
        expect(line.combo_line_ids.length).toBe(1);
        expect(line.combo_line_ids[0].l10n_it_fiskaly_vat_exemption).toBe("CAUSE_1");
        expect(template.id in store.l10nItFiskalyComboExemptions).toBe(false);
    });

    test("a combo child without a chosen exemption cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const { template, comboOpts } = createExemptCombo(store);
        const line = await store.addLineToCurrentOrder(
            { product_tmpl_id: template },
            { comboOpts },
            false
        );
        expect(Boolean(line.combo_line_ids[0].l10n_it_fiskaly_vat_exemption)).toBe(false);
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    const mountExemptConfigurator = async (store) => {
        const tax = createTax(store, { id: 9410, name: "IT 0% configurator", amount: 0 });
        const items = ["First", "Second"].map((name) => {
            const { variant } = createComboItemProduct(store, { name });
            variant.product_tmpl_id.taxes_id = [tax];
            return { product: variant };
        });
        const { template, combos } = createComboTemplate(store, {
            name: "Configurable combo",
            combos: [{ name: "Main", items }],
        });
        const popup = await mountWithCleanup(ComboConfiguratorPopup, {
            props: { productTemplate: template, getPayload: () => {}, close: () => {} },
        });
        return { popup, comboItem: combos[0].combo_item_ids[0] };
    };

    test("clicking an exempt combo item asks for its exemption", async () => {
        const store = await setupFiskalyStore();
        const { popup, comboItem } = await mountExemptConfigurator(store);
        store.dialog.add = (component, props) => props.getPayload("CAUSE_1");
        await popup.onClickProduct(comboItem.product_id, comboItem);
        expect(popup.state.qty[comboItem.combo_id.id][comboItem.id]).toBe(1);
        expect(popup.exemptions[comboItem.id]).toBe("CAUSE_1");
    });

    test("an exempt combo item is not selected without an exemption", async () => {
        const store = await setupFiskalyStore();
        const { popup, comboItem } = await mountExemptConfigurator(store);
        store.dialog.add = (component, props, options) => options.onClose();
        await popup.onClickProduct(comboItem.product_id, comboItem);
        expect(popup.state.qty[comboItem.combo_id.id][comboItem.id]).toBe(0);
        expect(comboItem.id in popup.exemptions).toBe(false);
    });

    test("taxes passed in vals win over the product's own taxes", async () => {
        const store = await setupFiskalyStore();
        const tax = createTax(store, { id: 9200, name: "IT 10%", amount: 10 });
        const product = createTestProduct(store, { name: "Untaxed product", taxes_id: [] });
        const taxes = store.l10nItFiskalyLineTaxes({
            product_tmpl_id: product,
            tax_ids: [["link", tax]],
        });
        expect(taxes.length).toBe(1);
        expect(taxes[0].amount).toBe(10);
    });

    test("empty taxes passed in vals win over the product's own taxes", async () => {
        const store = await setupFiskalyStore();
        const tax = createTax(store, { id: 9202, name: "IT 22% emptied", amount: 22 });
        const product = createTestProduct(store, { name: "Taxed product", taxes_id: [tax] });
        expect(store.l10nItFiskalyLineTaxes({ product_tmpl_id: product, tax_ids: [] })).toEqual([]);
    });

    test("a line carrying an allowed rate in vals is added silently", async () => {
        const store = await setupFiskalyStore();
        const tax = createTax(store, { id: 9201, name: "IT 4%", amount: 4 });
        const product = createTestProduct(store, { name: "Settled line", taxes_id: [] });
        const exemption = await store.l10nItFiskalyVatExemption({
            product_tmpl_id: product,
            tax_ids: [["link", tax]],
        });
        expect(exemption).toBe(null);
    });

    const createTaxedProduct = (store, id, price = 10) => {
        const tax = createTax(store, { id, name: `IT 22% ${id}`, amount: 22 });
        return createTestProduct(store, { name: `Product ${id}`, price, taxes_id: [tax] });
    };

    const spyPay = (store) => {
        const result = { dialogs: 0, navigated: false };
        store.dialog.add = () => result.dialogs++;
        store.navigate = () => {
            result.navigated = true;
        };
        return result;
    };

    test("a sale with a negative quantity cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9300);
        await store.addLineToCurrentOrder({ product_tmpl_id: product, qty: -1 }, {}, false);
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    test("a sale with a negative price cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9301);
        await store.addLineToCurrentOrder({ product_tmpl_id: product }, {}, false);
        await store.addLineToCurrentOrder(
            { product_tmpl_id: createTaxedProduct(store, 9302), price_unit: -1 },
            {},
            false
        );
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    test("a positive sale can be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9303);
        await store.addLineToCurrentOrder({ product_tmpl_id: product }, {}, false);
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(0);
        expect(result.navigated).toBe(true);
    });

    test("a global discount on a sale can be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9304);
        const discount = createTaxedProduct(store, 9305, 0);
        store.config.discount_product_id = discount.product_variant_ids[0];
        await store.addLineToCurrentOrder({ product_tmpl_id: product }, {}, false);
        await store.addLineToCurrentOrder({ product_tmpl_id: discount, price_unit: -2 }, {}, false);
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(0);
        expect(result.navigated).toBe(true);
    });

    test("a sale whose discount exceeds its total cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9306);
        const discount = createTaxedProduct(store, 9307, 0);
        store.config.discount_product_id = discount.product_variant_ids[0];
        await store.addLineToCurrentOrder({ product_tmpl_id: product }, {}, false);
        await store.addLineToCurrentOrder(
            { product_tmpl_id: discount, price_unit: -20 },
            {},
            false
        );
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    test("a refund with negative quantities can be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9308);
        const originalLine = await store.addLineToCurrentOrder(
            { product_tmpl_id: product },
            {},
            false
        );
        store.addNewOrder({ is_refund: true });
        await store.addLineToCurrentOrder(
            { product_tmpl_id: product, qty: -1, refunded_orderline_id: originalLine },
            {},
            false
        );
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(0);
        expect(result.navigated).toBe(true);
    });

    test("a refund containing a new sale cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const product = createTaxedProduct(store, 9309);
        const originalLine = await store.addLineToCurrentOrder(
            { product_tmpl_id: product },
            {},
            false
        );
        store.addNewOrder({ is_refund: true });
        await store.addLineToCurrentOrder(
            { product_tmpl_id: product, qty: -1, refunded_orderline_id: originalLine },
            {},
            false
        );
        await store.addLineToCurrentOrder(
            { product_tmpl_id: createTaxedProduct(store, 9310) },
            { force: true },
            false
        );
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    const addExemptLine = async (store, id) => {
        const tax = createTax(store, { id, name: `IT 0% ${id}`, amount: 0 });
        const { template } = createTestProduct(store, { name: `Exempt ${id}`, taxes_id: [tax] });
        const addDialog = store.dialog.add;
        store.dialog.add = (component, props) => props.getPayload("CAUSE_1");
        const line = await store.addLineToCurrentOrder({ product_tmpl_id: template }, {}, false);
        store.dialog.add = addDialog;
        return line;
    };

    test("a line without a VAT rate or an exemption cannot be paid", async () => {
        const store = await setupFiskalyStore();
        const line = await addExemptLine(store, 9500);
        line.l10n_it_fiskaly_vat_exemption = false;
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(1);
        expect(result.navigated).toBe(false);
    });

    // Fast payment buttons validate the order directly through OrderPaymentValidation,
    // without going through pos.pay(): the fiskaly checks must run there too, otherwise an
    // order without VAT or exemption, or a negative sale, would be sent to fiskaly.
    const fastPayment = (store) =>
        new OrderPaymentValidation({
            pos: store,
            orderUuid: store.getOrder().uuid,
            fastPaymentMethod: store.models["pos.payment.method"].getFirst(),
        });

    test("a fast payment of a line without a VAT rate or an exemption is refused", async () => {
        const store = await setupFiskalyStore();
        const line = await addExemptLine(store, 9502);
        line.l10n_it_fiskaly_vat_exemption = false;
        const result = spyPay(store);
        expect(await fastPayment(store).isOrderValid(false)).toBe(false);
        expect(result.dialogs).toBe(1);
    });

    test("a fast payment of a negative sale is refused", async () => {
        const store = await setupFiskalyStore();
        const { template } = createTaxedProduct(store, 9503);
        await store.addLineToCurrentOrder({ product_tmpl_id: template, qty: -1 }, {}, false);
        const result = spyPay(store);
        expect(await fastPayment(store).isOrderValid(false)).toBe(false);
        expect(result.dialogs).toBe(1);
    });

    test("a line with an exemption can be paid", async () => {
        const store = await setupFiskalyStore();
        const line = await addExemptLine(store, 9501);
        expect(line.l10n_it_fiskaly_vat_exemption).toBe("CAUSE_1");
        const result = spyPay(store);
        await store.pay();
        expect(result.dialogs).toBe(0);
        expect(result.navigated).toBe(true);
    });

    test("nothing is checked when the register is not registered with fiskaly", async () => {
        const store = await setupFiskalyStore();
        store.config.l10n_it_fiskaly_system_id = false;
        const product = createTestProduct(store, { name: "Untaxed", taxes_id: [] });
        const line = await store.addLineToCurrentOrder({ product_tmpl_id: product }, {}, false);
        expect(line).toBeTruthy();
    });
});
