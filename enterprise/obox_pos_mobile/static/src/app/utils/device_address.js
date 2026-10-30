import { mobileNative } from "@pos_mobile_android/app/utils/native";
import { debounce } from "@web/core/utils/timing";

const LOOPBACK = "127.0.0.1";
const OWN_STATUS_CACHE_MS = 2000;
const ADDRESS_RE = /^(\w+:\/\/)?([^/:]+)(:\d+)?(.*)$/;

let ownStatus;
const forgetOwnStatus = debounce(() => (ownStatus = undefined), OWN_STATUS_CACHE_MS);

function getOwnStatus() {
    if (ownStatus === undefined) {
        ownStatus = mobileNative.getDeviceManagerStatus().catch(() => null);
    }
    forgetOwnStatus();
    return ownStatus;
}

const normalizeSerial = (serial) => (serial || "").trim().toUpperCase();

export async function resolveDeviceAddress(address, oboxSerial) {
    const match = address && address.match(ADDRESS_RE);
    if (!match || !mobileNative.getDeviceManagerStatus) {
        return address;
    }
    const own = await getOwnStatus();
    if (!own) {
        return address;
    }
    const [, scheme = "", host, port = "", rest] = match;
    const serial = normalizeSerial(oboxSerial);
    if (serial ? serial !== normalizeSerial(own.serial) : host !== own.ip) {
        return address;
    }
    const ownPort = serial && own.port ? `:${own.port}` : port;
    return `${scheme}${LOOPBACK}${ownPort}${rest}`;
}
