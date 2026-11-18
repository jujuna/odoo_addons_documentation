import { Component, onWillStart, signal, t, useOnChange, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { parseInteger } from "@web/views/fields/parsers";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";

export class BarcodeGenerateLotDialog extends Component {
    static template = "stock_barcode.barcode_generate_lot_dialog";
    props = useProps({
        model: t.object(),
        move: t.object(),
        line: t.object(),
        nextCustomSerialNumber: t.string(),
        remainingUnassignedLots: t.number(),
        close: t.function(),
    });
    static components = { Dialog };

    setup() {
        this.orm = useService("orm");
        this.ui = useService("ui");
        this.isLotTracking = this.props.line.product_id.tracking === "lot";
        this.title = this.isLotTracking
            ? _t("Generate Lot numbers")
            : _t("Generate Serial numbers");
        this.generationMode = signal(
            this.props.model.pickingTypeId.barcode_default_snln_generation
        );
        this.nextSerial = signal(this.props.nextCustomSerialNumber);
        this.qtyReceived = signal(this.qtyReceivedDefault);
        this.qtyPerLot = signal(this.qtyPerLotDefault);

        onWillStart(async () => {
            this.displayUOM = await user.hasGroup("uom.group_uom");
        });

        useOnChange(
            () => [this.generationMode()],
            (value) => this._onChangeGenerationMode(value)
        );
        useOnChange(
            () => [this.qtyReceived()],
            (value) => this._onChangeQtyReceived(value)
        );
    }

    get qtyReceivedDefault() {
        if (this.generationMode() === "only_one") {
            return this.isLotTracking ? this.props.remainingUnassignedLots : 1;
        }
        return this.props.remainingUnassignedLots;
    }

    get qtyPerLotDefault() {
        if (this.generationMode() === "only_one") {
            return this.isLotTracking ? Math.max(this.props.remainingUnassignedLots, 0) : 1;
        }
        return this.isLotTracking ? Math.max(this.props.remainingUnassignedLots, 0) : 1;
    }

    async _onValidate() {
        const parseMethod = this.isLotTracking ? parseFloat : parseInteger;
        const count =
            parseMethod("" + ((this.isLotTracking && this.qtyPerLot()) || this.qtyReceived())) || 0;
        const qtyToProcess = parseMethod("" + this.qtyReceived()) || 0;
        await this.props.model.generateLots(
            this.props.move,
            this.nextSerial(),
            qtyToProcess,
            count,
            this.generationMode()
        );
        this.props.close();
    }

    _onChangeGenerationMode() {
        this.qtyReceived.set(this.qtyReceivedDefault);
        this.qtyPerLot.set(this.qtyPerLotDefault);
    }

    _onChangeQtyReceived(value) {
        if (this.isLotTracking && this.qtyPerLot() > value) {
            this.qtyPerLot.set(value);
        }
    }
}
