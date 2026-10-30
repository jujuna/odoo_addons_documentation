import { onMounted, onWillUnmount } from "@odoo/owl";
import mobile from "@web_mobile/js/services/core";

const POLL_DELAY_MS = 100;

export function useNfcReader(onRead, { secure = () => false } = {}) {
    const { enableNfcReader, getNfcReaderData, disableNfcReader } = mobile.methods;
    if (!enableNfcReader) {
        return;
    }
    const poll = async () => {
        try {
            const { success, data } = await getNfcReaderData({ secure: secure() });
            if (success) {
                data.forEach((read) => onRead(read.uid, read.secure));
            }
        } catch (error) {
            console.error(error);
        }
    };
    let interval;
    onMounted(() => {
        enableNfcReader({ secure: secure() }).catch(console.error);
        interval = setInterval(poll, POLL_DELAY_MS);
    });
    onWillUnmount(() => {
        clearInterval(interval);
        disableNfcReader().catch(console.error);
    });
}
