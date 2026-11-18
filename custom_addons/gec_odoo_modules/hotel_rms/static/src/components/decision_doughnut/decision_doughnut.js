import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useChart } from "@web/core/utils/chart_hook";
import { baseOptions, chartTheme } from "../../utils/chart_utils";

export class DecisionDoughnut extends Component {
    static template = "hotel_rms.DecisionDoughnut";
    props = useProps({
        accepted: t.number().optional(0),
        edited: t.number().optional(0),
        rejected: t.number().optional(0),
        centre: t.string().optional(""),
        centreNote: t.string().optional(""),
        onSlice: t.function().optional(() => {}),
    });
    chart = useChart(() => this.getConfig());

    get parts() {
        const { accepted, edited, rejected } = this.props;
        return [
            { key: "accepted", label: _t("Accepted"), count: accepted },
            { key: "edited", label: _t("Own price"), count: edited },
            { key: "rejected", label: _t("Rejected"), count: rejected },
        ];
    }

    getConfig() {
        const theme = chartTheme();
        const options = baseOptions(theme);
        const colors = [theme.success, theme.info, theme.muted];
        return {
            type: "doughnut",
            data: {
                labels: this.parts.map((part) => `${part.label} ${part.count}`),
                datasets: [{ data: this.parts.map((part) => part.count), backgroundColor: colors, borderWidth: 0 }],
            },
            options: {
                ...options,
                cutout: "70%",
                interaction: { mode: "nearest", intersect: true },
                onClick: (_event, elements) => {
                    if (elements.length) {
                        this.props.onSlice(this.parts[elements[0].index].key);
                    }
                },
                plugins: {
                    ...options.plugins,
                    tooltip: {
                        ...options.plugins.tooltip,
                        callbacks: { label: (item) => `${this.parts[item.dataIndex].label}: ${item.parsed}` },
                    },
                },
            },
        };
    }
}
