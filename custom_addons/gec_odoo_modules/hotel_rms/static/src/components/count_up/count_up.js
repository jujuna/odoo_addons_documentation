import { Component, onMounted, onWillUnmount, proxy, t, useOnChange, useProps } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { reducedMotion } from "../../utils/chart_utils";

const DURATION = 600;

export class CountUp extends Component {
    static template = "hotel_rms.CountUp";
    props = useProps({
        value: t.number(),
        format: t.function().optional(() => (value) => String(Math.round(value))),
    });

    setup() {
        this.state = proxy({ shown: reducedMotion() ? this.props.value : 0 });
        onMounted(() => this.run(this.state.shown, this.props.value));
        useOnChange(
            () => [this.props.value],
            (value) => this.run(this.state.shown, value),
            { initialRun: false }
        );
        onWillUnmount(() => browser.cancelAnimationFrame(this.frame));
    }

    run(from, to) {
        browser.cancelAnimationFrame(this.frame);
        if (reducedMotion() || from === to) {
            this.state.shown = to;
            return;
        }
        const start = browser.performance.now();
        const step = (now) => {
            const progress = Math.min(1, (now - start) / DURATION);
            this.state.shown = from + (to - from) * (1 - (1 - progress) ** 4);
            if (progress < 1) {
                this.frame = browser.requestAnimationFrame(step);
            }
        };
        this.frame = browser.requestAnimationFrame(step);
    }
}
