import { patch } from "@web/core/utils/patch";
import { SignablePDFIframe } from "@sign/components/sign_request/signable_PDF_iframe";

// The desktop app stamps the real signature, so pre-fill the signer's signature fields
// to skip the "Adopt Your Signature" dialog. The name mark stays in the PDF as a placement guide.
patch(SignablePDFIframe.prototype, {
    postRender() {
        super.postRender(...arguments);
        if (this.readonly || this.props.authMethod !== "geoeid") {
            return;
        }
        const image = this._geoeidNameImage(this.signerName || this.currentRoleName || "");
        for (const page in this.signItems) {
            for (const signItem of Object.values(this.signItems[page])) {
                const type = this.signItemTypesById[signItem.data.type_id];
                const isSignature = type.item_type === "signature" || type.item_type === "initial";
                if (
                    isSignature &&
                    signItem.data.responsible === this.currentRole &&
                    !signItem.el.dataset.signature
                ) {
                    this.fillItemWithSignature(signItem.el, image);
                }
            }
        }
        this.checkSignItemsCompletion();
    },

    _geoeidNameImage(name) {
        const canvas = document.createElement("canvas");
        canvas.width = 400;
        canvas.height = 100;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#000000";
        ctx.textBaseline = "middle";
        const maxWidth = canvas.width - 20;
        let fontSize = 40;
        do {
            ctx.font = `italic ${fontSize}px serif`;
            fontSize -= 2;
        } while (fontSize > 14 && ctx.measureText(name).width > maxWidth);
        ctx.fillText(name, 10, 55, maxWidth);
        return canvas.toDataURL("image/png");
    },
});
