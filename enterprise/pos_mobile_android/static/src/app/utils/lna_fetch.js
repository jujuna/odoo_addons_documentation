import { mobileNative } from "@pos_mobile_android/app/utils/native";
import { isPrivateIp } from "@point_of_sale/app/utils/init_lna";

/**
 * Local Network Access from the app. The WebView cannot reach the local
 * network itself, so the requests that declare a targetAddressSpace are
 * performed by the app.
 */
export async function mobileLnaFetch(input, init = {}) {
    const request = new Request(input, {
        method: init.method,
        headers: init.headers,
        body: init.body,
        signal: init.signal,
    });
    const headers = {};
    request.headers.forEach((value, key) => (headers[key] = value));
    const body = init.body == null ? null : await request.text();
    if (body && !headers["content-type"]) {
        headers["content-type"] = "text/xml; charset=utf-8";
    }
    const reply = await mobileNative.lnaFetch({
        url: request.url,
        params: {
            method: request.method,
            headers,
            body,
            "no-cors": init.mode === "no-cors",
        },
    });
    if (!reply?.status) {
        throw new TypeError(reply?.message || "native request failed");
    }
    return new Response(reply.body || "", { status: reply.status, headers: reply.headers || {} });
}

function isLocalNetworkRequest(input, init) {
    if (!init?.targetAddressSpace) {
        return false;
    }
    try {
        return isPrivateIp(new URL(input instanceof Request ? input.url : input).hostname);
    } catch {
        return false;
    }
}

export function grantLnaPermission(target = navigator) {
    try {
        const permissions = target.permissions;
        const query = permissions?.query?.bind(permissions);
        const lnaQuery = (descriptor) => {
            if (descriptor?.name === "local-network-access") {
                return Promise.resolve({ state: "granted" });
            }
            return query ? query(descriptor) : Promise.resolve(new EventTarget());
        };
        if (permissions) {
            permissions.query = lnaQuery;
        } else {
            Object.defineProperty(target, "permissions", {
                value: { query: lnaQuery },
                configurable: true,
            });
        }
    } catch (error) {
        console.error("Failed to grant the local network access permission", error);
    }
}

if (mobileNative.lnaFetch) {
    try {
        const browserFetch = window.fetch.bind(window);
        window.fetch = (input, init) =>
            isLocalNetworkRequest(input, init)
                ? mobileLnaFetch(input, init)
                : browserFetch(input, init);
        grantLnaPermission();
    } catch (error) {
        console.error("Failed to patch fetch for local network access", error);
    }
}
