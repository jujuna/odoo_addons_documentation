import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { Dialog } from "@web/core/dialog/dialog";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";

const POLL_INTERVAL = 3000;
const MAX_POLLS = 200; // ~10 min, matches the server-side one-time token TTL

export class GeoeidSignerDialog extends Component {
    static template = "id_ge_sign.GeoeidSignerDialog";
    static components = { Dialog };
    props = useProps({
        requestID: t.number(),
        accessToken: t.string(),
        signatureValues: t.any().optional(),
        frameValues: t.any().optional(),
        onSigned: t.function(),
        close: t.function(),
    });

    setup() {
        this.ui = useService("ui");
        // phase: launching -> waiting -> (signed handled by close) | error
        this.state = proxy({ phase: "launching", launchUrl: false, error: false });
        this.pollCount = 0;
        this.closed = false;
        // Not awaited, so "Preparing..." renders while launch runs.
        onWillStart(() => {
            this.launch();
        });
        onWillUnmount(() => {
            this.closed = true;
            browser.clearTimeout(this.timeout);
            this.cancelServer();
        });
    }

    async launch() {
        if (this.closed) {
            return;
        }
        this.state.phase = "launching";
        this.state.error = false;
        this.pollCount = 0;
        const route = `/sign/sign/${encodeURIComponent(
            this.props.requestID
        )}/${encodeURIComponent(this.props.accessToken)}`;
        let response;
        try {
            response = await rpc(
                route,
                { signature: this.props.signatureValues, frame: this.props.frameValues },
                { silent: true }
            );
        } catch (error) {
            if (this.closed) {
                return;
            }
            this.state.phase = "error";
            this.state.error = error.data
                ? error.data.message
                : _t("Could not reach Odoo to start Georgian ID Card signing.");
            return;
        }
        if (this.closed) {
            await this.cancelServer();
            return;
        }
        if (!response.success) {
            this.state.phase = "error";
            this.state.error = response.message || _t("Could not start Georgian ID Card signing.");
            return;
        }
        this.state.launchUrl = response.authorization_url;
        this.state.phase = "waiting";
        this.openApp();
        this.poll();
    }

    openApp() {
        if (this.closed || !this.state.launchUrl) {
            return;
        }
        // A custom-scheme link opens the app without leaving the signing page.
        const link = document.createElement("a");
        link.href = this.state.launchUrl;
        link.style.display = "none";
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    poll() {
        if (this.closed) {
            return;
        }
        if (this.pollCount >= MAX_POLLS) {
            this.state.phase = "error";
            this.state.error = _t("Timed out waiting for the signature. Please try again.");
            this.cancelServer();
            return;
        }
        this.pollCount++;
        const route = `/sign/geoeid/status/${encodeURIComponent(
            this.props.requestID
        )}/${encodeURIComponent(this.props.accessToken)}`;
        this.timeout = browser.setTimeout(async () => {
            if (this.closed) {
                return;
            }
            let status;
            try {
                status = await rpc(route, {}, { silent: true });
            } catch {
                if (this.closed) {
                    return;
                }
                this.state.phase = "error";
                this.state.error = _t("Could not check the signing status. Please try again.");
                return;
            }
            if (this.closed) {
                return;
            }
            if (status.state === "signed") {
                // Closing after onSigned re-renders the dialogs and destroys the next one while it loads.
                await this.props.close();
                this.props.onSigned();
            } else if (status.state === "failed") {
                this.state.phase = "error";
                this.state.error = _t(
                    "The ID card signature was not accepted. Try again with your own ID card, or ask the sender for a new link."
                );
            } else {
                this.poll();
            }
        }, POLL_INTERVAL);
    }

    async cancelServer() {
        const route = `/sign/geoeid/cancel/${encodeURIComponent(
            this.props.requestID
        )}/${encodeURIComponent(this.props.accessToken)}`;
        try {
            await rpc(route, {}, { silent: true });
        } catch {
            // Best effort: the token expires server-side anyway.
        }
    }

    async cancel() {
        this.closed = true;
        browser.clearTimeout(this.timeout);
        await this.cancelServer();
        this.props.close();
    }

    get dialogProps() {
        return {
            size: "md",
            title: _t("Sign with Georgian ID Card"),
            fullscreen: this.ui.isSmall,
        };
    }
}
