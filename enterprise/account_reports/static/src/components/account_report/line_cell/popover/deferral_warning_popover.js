import { Component, useProps, t } from "@odoo/owl";

export class DeferralWarningPopover extends Component {
    static template = "account_reports.DeferralWarningPopover";
    props = useProps({
        close: t.function(),
        warning_action: t.function(),
    });
}
