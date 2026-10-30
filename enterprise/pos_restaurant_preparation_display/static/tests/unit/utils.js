import { createPrepDisplayTicket } from "@pos_enterprise/../tests/unit/utils";

export const createPrepTicketWithCourses = async (store) => {
    const course1 = { id: 1, name: "Starters", index: 1, fired: false };
    const course2 = { id: 2, name: "Main Course", index: 2, fired: false };

    await createPrepDisplayTicket(store, {
        lines: [
            {
                qty: 1,
                product_id: 5,
                full_product_name: "Caesar Salad",
            },
            {
                qty: 1,
                product_id: 6,
                full_product_name: "Steak",
            },
        ],
    });

    // Attach course records to the prep lines so the patch can resolve them
    const prepLines = store.data.models["pos.prep.line"].getAll();
    prepLines[0].pos_order_line_id.course_id = course1;
    prepLines[1].pos_order_line_id.course_id = course2;
};
