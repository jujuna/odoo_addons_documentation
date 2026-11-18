import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Document } from "@sign/components/sign_request/document_signable";
import { GeoeidSignerDialog } from "@id_ge_sign/dialogs/geoeid_signer_dialog";
import { NextDirectSignDialog, openAllSetDirectSignDialog } from "@sign/dialogs/dialogs";

patch(Document.prototype, {
    async getAuthDialog() {
        if (this.authMethod === "geoeid") {
            return {
                component: GeoeidSignerDialog,
                props: {
                    requestID: this.requestID,
                    accessToken: this.accessToken,
                    signatureValues: this.signatureInfo.signatureValues,
                    frameValues: this.signatureInfo.frameValues,
                    onSigned: () => {
                        this.validateButton.removeAttribute("disabled");
                        this.disableItems();
                        const nameList = this.signInfo.get("nameList");
                        if (nameList && nameList.length > 0) {
                            this.signInfo.set({
                                lastSignedName: this.signerName,
                                lastEmailedName: false,
                            });
                            this.dialog.add(NextDirectSignDialog);
                        } else if (this.signInfo.get("someSignersEmailed")) {
                            openAllSetDirectSignDialog(this.env, this.signInfo);
                        } else {
                            this.openThankYouDialog();
                        }
                    },
                },
            };
        }
        return super.getAuthDialog(...arguments);
    },

    async _signDocuments() {
        // Public link: the card authenticates the signer, so skip the name/email dialog.
        if (
            this.isUnknownPublicUser &&
            this.authMethod === "geoeid" &&
            !this.signatureInfo.hasNoSignature
        ) {
            this.validateButton.setAttribute("disabled", true);
            this.geoeidAttemptId ||= crypto.randomUUID();
            let response;
            try {
                response = await rpc(
                    `/sign/geoeid/public/${encodeURIComponent(
                        this.signInfo.get("documentId")
                    )}/${encodeURIComponent(this.signInfo.get("signRequestToken"))}`,
                    { attempt_id: this.geoeidAttemptId },
                    { silent: true }
                );
            } catch (error) {
                response = { error: error.data?.message };
            }
            if (!response?.requestID) {
                this.validateButton.removeAttribute("disabled");
                this.dialog.add(AlertDialog, {
                    body: response?.error || _t("Could not start Georgian ID Card signing."),
                });
                return;
            }
            this.signInfo.set({
                documentId: response.requestID,
                signRequestToken: response.requestToken,
                signRequestItemToken: response.accessToken,
            });
            this.requestID = response.requestID;
            this.requestToken = response.requestToken;
            this.accessToken = response.accessToken;
            if (this.coords) {
                await rpc(
                    `/sign/save_location/${response.requestID}/${response.accessToken}`,
                    this.coords
                );
            }
            this.isUnknownPublicUser = false;
            return this._signDocuments();
        }
        return super._signDocuments(...arguments);
    },
});
