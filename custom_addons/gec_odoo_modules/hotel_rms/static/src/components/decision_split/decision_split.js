import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class DecisionSplit extends Component {
    static template = "hotel_rms.DecisionSplit";
    props = useProps({
        accepted: t.number().optional(0),
        edited: t.number().optional(0),
        rejected: t.number().optional(0),
    });

    get parts() {
        const { accepted, edited, rejected } = this.props;
        const parts = [
            { key: "accepted", label: _t("Accepted"), count: accepted },
            { key: "edited", label: _t("Own price"), count: edited },
            { key: "rejected", label: _t("Rejected"), count: rejected },
        ];
        const total = accepted + edited + rejected;
        return parts.map((part) => ({ ...part, style: `width: ${total ? (part.count / total) * 100 : 0}%` }));
    }
}
