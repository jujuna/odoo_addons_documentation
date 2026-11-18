import { Component, t, useProps } from "@odoo/owl";

export class Sparkline extends Component {
    static template = "hotel_rms.Sparkline";
    props = useProps({ values: t.array(t.number()) });

    get points() {
        const { values } = this.props;
        const max = Math.max(...values, 1);
        return values
            .map((value, index) => `${(index / (values.length - 1)) * 100},${22 - (value / max) * 20}`)
            .join(" ");
    }
}
