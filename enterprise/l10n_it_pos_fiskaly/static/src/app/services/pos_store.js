import { PosStore } from "@point_of_sale/app/services/pos_store";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError, RPCError } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";

const CONNECTION_LOSS_URL = "https://workspace.fiskaly.com/sign-it/2026-06-01/connection-loss/";

const VAT_RATE_PERCENTAGES = [22, 10, 5, 4];

// Keep in sync with VAT_EXEMPTIONS in models/account_tax.py.
const vatExemptions = () => [
    { code: "NOT_SUBJECT", description: _t("Not subject (Non soggette)") },
    { code: "NOT_TAXABLE", description: _t("Not taxable (Non imponibili)") },
    { code: "CAUSE_1", description: _t("Exempt (Esenti)") },
    { code: "CAUSE_2", description: _t("Exclusive Art. 15") },
    { code: "CAUSE_3", description: _t("Marginal scheme (Regime del margine)") },
    { code: "CAUSE_4", description: _t("Other (Altre non IVA)") },
];

patch(PosStore.prototype, {
    async afterProcessServerData() {
        this.l10nItFiskalyTaxpayerMode = false;
        this.l10nItFiskalyComboExemptions = {};
        if (this.config.l10nItFiskalyActive) {
            try {
                this.l10nItFiskalyTaxpayerMode = await this.data.call(
                    "pos.config",
                    "l10n_it_fiskaly_get_taxpayer_mode",
                    [this.config.id]
                );
            } catch (error) {
                if (error instanceof RPCError) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Fiskaly SIGN IT"),
                        body: error.data.message,
                    });
                } else if (!(error instanceof ConnectionLostError)) {
                    throw error;
                }
            }
            if (this.l10nItFiskalyTaxpayerMode && this.l10nItFiskalyTaxpayerMode !== "OPERATIVE") {
                this.dialog.add(AlertDialog, {
                    title: _t("Fiskaly SIGN IT"),
                    body: _t(
                        "The fiskaly taxpayer of this company is %s: receipts cannot be transmitted" +
                            " to the Agenzia delle Entrate. Please check the fiskaly hub for more" +
                            " information.",
                        this.l10nItFiskalyTaxpayerMode
                    ),
                });
            }
        }
        return super.afterProcessServerData(...arguments);
    },

    l10nItFiskalyProduct(vals) {
        return vals.product_id || vals.product_tmpl_id?.product_variant_ids[0];
    },

    l10nItFiskalyLineTaxes(vals) {
        if (vals.tax_ids) {
            return vals.tax_ids
                .filter((command) => command[0] === "link")
                .flatMap((command) => command.slice(1));
        }
        const order = this.getOrder();
        const taxes = this.l10nItFiskalyProduct(vals)?.taxes_id || [];
        return order?.fiscal_position_id
            ? order.fiscal_position_id.getTaxesAfterFiscalPosition(taxes)
            : taxes;
    },

    async l10nItFiskalyVatExemption(vals) {
        const product = this.l10nItFiskalyProduct(vals);
        if (product?.isCombo()) {
            return null;
        }
        if (product && product === this.config.tip_product_id) {
            return "NOT_SUBJECT";
        }
        const taxes = this.l10nItFiskalyLineTaxes(vals);
        const tax = taxes[0];
        if (tax && tax.amount) {
            if (!VAT_RATE_PERCENTAGES.includes(tax.amount)) {
                this.dialog.add(AlertDialog, {
                    title: _t("Fiskaly SIGN IT"),
                    body: _t(
                        "%(product)s cannot be added: %(tax)s does not match any VAT rate accepted" +
                            " by the Agenzia delle Entrate.",
                        { product: product.display_name, tax: tax.name }
                    ),
                });
                return false;
            }
            return null;
        }
        if (tax?.l10n_it_fiskaly_vat_exemption) {
            return tax.l10n_it_fiskaly_vat_exemption;
        }
        return await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Select a VAT exemption"),
            list: vatExemptions().map((exemption) => ({
                id: exemption.code,
                label: exemption.description,
                item: exemption.code,
            })),
        });
    },

    l10nItFiskalyAllowsNegativeLine(line) {
        return line.product_id === this.config.discount_product_id;
    },

    l10nItFiskalyCheckOrder(order) {
        const isRefund = order.isRefund;
        if (
            (isRefund &&
                order.lines.some(
                    (line) =>
                        this.currency.isPositive(line.prices.total_included) &&
                        !this.l10nItFiskalyAllowsNegativeLine(line)
                )) ||
            (!isRefund &&
                (this.currency.isNegative(order.priceIncl) ||
                    order.lines.some(
                        (line) =>
                            (line.qty < 0 || this.currency.isNegative(line.price_unit)) &&
                            !this.l10nItFiskalyAllowsNegativeLine(line)
                    )))
        ) {
            this.dialog.add(AlertDialog, {
                title: _t("Fiskaly SIGN IT"),
                body: _t(
                    "The amount of the order must be positive for a sale and negative for a" +
                        " refund. Negative quantities and prices are only allowed on refunds."
                ),
            });
            return false;
        }
        const missing = order.lines.filter((line) => !this.l10nItFiskalyLineHasVat(line, order));
        if (missing.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Fiskaly SIGN IT"),
                body: _t(
                    "The following products have no VAT rate and no VAT exemption: %s." +
                        " Remove them and add them again to select a VAT exemption.",
                    missing.map((line) => line.getFullProductName()).join(", ")
                ),
            });
            return false;
        }
        return true;
    },

    async postSyncAllOrders(orders) {
        await super.postSyncAllOrders(...arguments);
        if (!this.config.l10nItFiskalyActive) {
            return;
        }
        const unsigned = orders.filter(
            (order) =>
                ["paid", "done"].includes(order.state) &&
                !order.l10n_it_fiskaly_record_id &&
                order.lines.some((line) => line.qty)
        );
        if (!unsigned.length) {
            return;
        }
        const manual = unsigned.filter(
            (order) => order.refunded_order_id && !order.refunded_order_id.l10n_it_fiskaly_record_id
        );
        const lost = unsigned.filter((order) => !manual.includes(order));
        this.dialog.add(AlertDialog, {
            title: _t("Fiskaly SIGN IT"),
            body: [
                manual.length && this.l10nItFiskalyManualDocumentBody(manual),
                lost.length && this.l10nItFiskalyConnectionLossBody(lost),
            ]
                .filter(Boolean)
                .join("\n\n"),
        });
    },

    l10nItFiskalyManualDocumentBody(orders) {
        return _t(
            "%(orders)s: the original receipt has no fiskaly record, this transaction was not" +
                " transmitted to the Agenzia delle Entrate.\n\nThe return or the cancellation is" +
                ' to be done manually from the "Fatture e Corrispettivi" portal with Fisconline' +
                ' credentials: section "Corrispettivi" → "Documento Commerciale Online" →' +
                ' "Genera il tuo documento" → "Tipo operazione" ("Reso" or "Annullo") →' +
                ' "Prosegui" under "Documento commerciale non recuperabile".',
            { orders: orders.map((order) => order.pos_reference).join(", ") }
        );
    },

    l10nItFiskalyConnectionLossBody(orders) {
        return _t(
            "%(orders)s: there has been an issue with SIGN IT, this transaction could not be" +
                " transmitted to the Agenzia delle Entrate.\n\nPlease ensure compliance by issuing" +
                " an electronic invoice through the SdI within 12 days of the transaction.\n\n%(url)s",
            {
                orders: orders.map((order) => order.pos_reference).join(", "),
                url: CONNECTION_LOSS_URL,
            }
        );
    },

    async pay() {
        if (this.config.l10nItFiskalyActive && !this.l10nItFiskalyCheckOrder(this.getOrder())) {
            return;
        }
        return super.pay(...arguments);
    },

    canEditPayment(_order) {
        return !this.config.l10nItFiskalyActive && super.canEditPayment(...arguments);
    },

    l10nItFiskalyLineHasVat(line, order) {
        if (line.combo_line_ids?.length || line.l10n_it_fiskaly_vat_exemption) {
            return true;
        }
        const taxes = order.fiscal_position_id
            ? order.fiscal_position_id.getTaxesAfterFiscalPosition(line.tax_ids)
            : line.tax_ids;
        return Boolean(taxes[0]?.amount);
    },

    async handleComboProduct(values, _order, _configure = true, _opts = {}) {
        const keepGoing = await super.handleComboProduct(...arguments);
        if (!this.config.l10nItFiskalyActive) {
            return keepGoing;
        }
        const exemptions = this.l10nItFiskalyComboExemptions[values.product_tmpl_id.id] || {};
        delete this.l10nItFiskalyComboExemptions[values.product_tmpl_id.id];
        if (keepGoing === false) {
            return keepGoing;
        }
        for (const [, childVals] of values.combo_line_ids || []) {
            const comboItemId = childVals.combo_item_id?.id;
            if (exemptions[comboItemId]) {
                childVals.l10n_it_fiskaly_vat_exemption = exemptions[comboItemId];
            }
        }
        return keepGoing;
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        if (!this.config.l10nItFiskalyActive) {
            return super.addLineToCurrentOrder(vals, opts, configure);
        }
        const exemption = await this.l10nItFiskalyVatExemption(vals);
        if (exemption === false || exemption === undefined) {
            return false;
        }
        const line = await super.addLineToCurrentOrder(vals, opts, configure);
        if (line && exemption) {
            line.l10n_it_fiskaly_vat_exemption = exemption;
        }
        return line;
    },
});
