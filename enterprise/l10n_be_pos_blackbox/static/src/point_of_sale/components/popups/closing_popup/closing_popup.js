import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(ClosePosPopup.prototype, {
    async closeSession() {
        // The session cannot be closed without signing its Z reports, so an
        // unreachable FDM must stop the closing before anything is done.
        if (this.pos.blackbox.isActive && !(await this.pos.blackbox.ping())) {
            this.dialog.add(AlertDialog, {
                title: _t("FDM Connection Error"),
                body: _t(
                    "Unable to contact the Fiscal Data Module. As the Z reports must be signed to close the register, please check the connection and try again."
                ),
            });
            return;
        }
        return super.closeSession();
    },
    /**
     * Only sign the Z reports if the session correctly closed in the backend, and if the FDM is active
     */
    async postCloseSession() {
        await super.postCloseSession();
        if (!this.pos.blackbox.isActive) {
            return;
        }
        try {
            this.ui.block();
            const usr = this.pos.l10nBeSigningInsz;
            await this.pos.workOutAllCashiers({ ignoreSessionState: true });
            await this.generateZReports(this.pos.session.id, usr);
            this.pos.resetCashier();
        } catch (error) {
            console.warn("Error during Z reports generation:", error);
        } finally {
            this.ui.unblock();
        }
    },
    async generateZReports(sessionId, usr) {
        // Ensure all pending signatures are sent before generating the reports
        await this.pos.blackbox.processSignatureQueue();
        const [saleDetails, userReportData] = await Promise.all([
            this.pos.data.call(
                "report.point_of_sale.report_saledetails",
                "get_sale_details",
                [false, false, false, [sessionId]],
                { before_closing: true }
            ),
            this.pos.data.call("pos.session", "get_l10n_be_user_report_data", [sessionId, true]),
        ]);

        // A Z report is signed only once per session: if already signed, it must not be signed again.
        if (!saleDetails.l10n_be_turnover_z_report_fdm_ref) {
            await this.pos.blackbox.signReportTurnoverZ.signWithDelay(
                this.pos.models,
                saleDetails,
                sessionId,
                usr
            );
        }
        if (!userReportData.l10n_be_user_z_report_fdm_ref) {
            await this.pos.blackbox.signReportUserZ.signWithDelay(
                this.pos.models,
                userReportData,
                sessionId,
                usr
            );
        }

        await this.pos.data.call("pos.session", "generate_l10n_z_reports_attachments", [
            sessionId,
            saleDetails,
            userReportData,
        ]);
    },
    async downloadSalesReport() {
        if (this.pos.blackbox.isActive) {
            return this.pos.openSalesReportsList(this.report, this.pos.session.id);
        } else {
            return super.downloadSalesReport();
        }
    },
    async openDetailsPopup() {
        if (this.pos.blackbox.isActive) {
            await this.pos.blackbox.signDrawerOpen.sign(
                this.pos.models,
                this.pos.l10nBeSigningInsz
            );
        }
        return super.openDetailsPopup();
    },
});
