import { Plugin, useConfig } from "@odoo/owl";

export class PayslipListPlugin extends Plugin {
    payRunId = useConfig("payRunId");
}
