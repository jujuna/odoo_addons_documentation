import { expect, test } from "@odoo/hoot";
import { setupPosEnv, getFilledOrder } from "@point_of_sale/../tests/unit/utils";
import { mountWithCleanup, patchWithCleanup, onRpc } from "@web/../tests/web_test_helpers";
import { ActionScreen } from "@point_of_sale/app/screens/action_screen";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

definePosModels();

test("ActionScreen => useEffect", async () => {
    const store = await setupPosEnv();
    onRpc("calendar.event", "action_open_booking_gantt_view", () => ({
        type: "ir.actions.act_window",
        name: "Gantt View",
    }));
    let actionCalled = null;
    patchWithCleanup(store.action, {
        async doAction(action) {
            actionCalled = action;
        },
    });
    await mountWithCleanup(ActionScreen, { props: { actionName: "manage-booking" } });
    expect(actionCalled).toEqual({
        type: "ir.actions.act_window",
        name: "Gantt View",
    });
});

test("ActionScreen => missing appointment type", async () => {
    const store = await setupPosEnv();
    store.config.appointment_type_id = false;

    // Case 1: If bookings become unavailable after a refresh or direct access, show an alert and redirect to the default page.
    store.navigate("ActionScreen", { actionName: "manage-booking" });
    await mountWithCleanup(ActionScreen, { props: { actionName: "manage-booking" } });
    expect(".modal-title").toHaveText("Booking Unavailable");
    expect(".modal-body").toHaveText("Please set an appointment type in the PoS Configuration.");
    // The invalid booking screen must return to the default page.
    expect(store.router.currentScreen()).toBe(store.defaultPage.page);

    // Case 2: Opening Bookings from another screen should show a warning without redirecting.
    const order = await getFilledOrder(store);
    store.navigate("PaymentScreen", { orderUuid: order.uuid });
    // The current page is PaymentScreen, while the default page is ProductScreen.
    expect(store.defaultPage.page).toBe("ProductScreen");
    expect(store.router.currentScreen()).toBe("PaymentScreen");

    await store.manageBookings();
    expect(".modal-title").toHaveText("Booking Unavailable");
    expect(".modal-body").toHaveText("Please set an appointment type in the PoS Configuration.");
    // The user must remain on the current screen instead of being redirected.
    expect(store.router.currentScreen()).toBe("PaymentScreen");
});
