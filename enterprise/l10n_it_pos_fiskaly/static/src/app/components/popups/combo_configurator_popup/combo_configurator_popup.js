import { ComboConfiguratorPopup } from "@point_of_sale/app/components/popups/combo_configurator_popup/combo_configurator_popup";
import { patch } from "@web/core/utils/patch";

patch(ComboConfiguratorPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.exemptions = {};
        if (!this.pos.config.l10nItFiskalyActive) {
            return;
        }
        for (const line of this.props.line?.getAllLinesInCombo() || []) {
            if (line.combo_item_id && line.l10n_it_fiskaly_vat_exemption) {
                this.exemptions[line.combo_item_id.id] = line.l10n_it_fiskaly_vat_exemption;
            }
        }
    },

    async l10nItFiskalyAskExemption(comboItem) {
        if (comboItem.id in this.exemptions) {
            return true;
        }
        const exemption = await this.pos.l10nItFiskalyVatExemption({
            product_id: comboItem.product_id,
        });
        if (exemption === false || exemption === undefined) {
            return false;
        }
        this.exemptions[comboItem.id] = exemption;
        return true;
    },

    async onClickProduct(product, combo_item) {
        if (
            this.pos.config.l10nItFiskalyActive &&
            !this.state.qty[combo_item.combo_id.id][combo_item.id] &&
            !(await this.l10nItFiskalyAskExemption(combo_item))
        ) {
            return;
        }
        return super.onClickProduct(...arguments);
    },

    async confirm() {
        if (this.pos.config.l10nItFiskalyActive) {
            const [itemsIncluded, itemsExtra] = this.getSelectedComboItems();
            for (const { combo_item_id } of [...itemsIncluded, ...itemsExtra]) {
                if (!(await this.l10nItFiskalyAskExemption(combo_item_id))) {
                    return;
                }
            }
            this.pos.l10nItFiskalyComboExemptions[this.props.productTemplate.id] = this.exemptions;
        }
        return super.confirm(...arguments);
    },
});
