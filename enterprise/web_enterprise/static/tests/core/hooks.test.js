import { animationFrame, describe, expect, test } from "@odoo/hoot";
import { Component, proxy, signal, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { useSticky } from "@web_enterprise/core/utils/hooks";

class StickyComponent extends Component {
    static template = xml`
        <div class="o_scroller overflow-auto" style="height: 100px;">
            <div style="height: 1000px;">
                <div t-if="this.state.show" class="o_sticky position-sticky top-0" t-att-class="{ o_is_sticky: this.sticky.isSticky }" t-ref="this.stickyRef">
                    Sticky
                </div>
            </div>
        </div>
    `;

    setup() {
        this.state = proxy({ show: true });
        this.stickyRef = signal.ref();
        this.sticky = useSticky(this.stickyRef);
    }
}

describe("useSticky", () => {
    test("is not sticky when the container is not scrolled", async () => {
        await mountWithCleanup(StickyComponent);
        expect(".o_sticky").not.toHaveClass("o_is_sticky");
    });

    test("follows the scroll position of the closest scrollable ancestor", async () => {
        await mountWithCleanup(StickyComponent);

        await contains(".o_scroller").scroll({ top: 100 });
        expect(".o_sticky").toHaveClass("o_is_sticky");

        await contains(".o_scroller").scroll({ top: 0 });
        expect(".o_sticky").not.toHaveClass("o_is_sticky");
    });

    test("is sticky when mounted in an already scrolled container", async () => {
        const component = await mountWithCleanup(StickyComponent);
        component.state.show = false;
        await animationFrame();

        await contains(".o_scroller").scroll({ top: 100 });
        expect(".o_scroller").toHaveProperty("scrollTop", 100);
        component.state.show = true;
        await animationFrame();
        await animationFrame();
        expect(".o_sticky").toHaveClass("o_is_sticky");
    });
});
