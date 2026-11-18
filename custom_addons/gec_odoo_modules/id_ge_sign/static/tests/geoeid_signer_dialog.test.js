import { describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, click, waitFor } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import {
    assignDialogTestEnv,
    makeServerError,
    makeTestApp,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { GeoeidSignerDialog } from "@id_ge_sign/dialogs/geoeid_signer_dialog";
import { Document } from "@sign/components/sign_request/document_signable";
import { SignablePDFIframe } from "@sign/components/sign_request/signable_PDF_iframe";

const requestID = 23;
const accessToken = "abc";
const signRoute = `/sign/sign/${requestID}/${accessToken}`;
const statusRoute = `/sign/geoeid/status/${requestID}/${accessToken}`;
const cancelRoute = `/sign/geoeid/cancel/${requestID}/${accessToken}`;
const launchUrl = "geoeid-unitool://x/sign/geoeid/init/T";
const signature = { 1: "sig" };
const frame = { 1: "frame" };
const POLL_INTERVAL = 3000;
const MAX_POLLS = 200;
const FAILED_SENTENCE =
    "The ID card signature was not accepted. Try again with your own ID card, or ask the sender for a new link.";

describe.current.tags("desktop");
defineMailModels();

let cancelCalls;
let linkClicks;

function mockCancelAndLinks() {
    cancelCalls = [];
    linkClicks = [];
    onRpc(cancelRoute, () => {
        cancelCalls.push(cancelRoute);
        return true;
    });
    patchWithCleanup(HTMLAnchorElement.prototype, {
        click() {
            linkClicks.push(this.getAttribute("href"));
        },
    });
}

async function mountDialog(additionalProps = {}) {
    assignDialogTestEnv();
    return mountWithCleanup(GeoeidSignerDialog, {
        props: {
            requestID,
            accessToken,
            signatureValues: signature,
            frameValues: frame,
            onSigned: () => expect.step("signed"),
            close: () => expect.step("close"),
            ...additionalProps,
        },
    });
}

function mockLaunch(response = { success: true, authorization_url: launchUrl }) {
    onRpc(signRoute, () => response);
}

test("mount posts signature and frame to the sign route", async () => {
    mockCancelAndLinks();
    onRpc(signRoute, async (request) => {
        const { params } = await request.json();
        expect.step("sign");
        expect(params).toEqual({ signature, frame });
        return { success: true, authorization_url: launchUrl };
    });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    expect.verifySteps(["sign"]);
});

test("the route encodes the request id and the access token", async () => {
    mockCancelAndLinks();
    onRpc("/sign/sign/7/a%2Fb", () => {
        expect.step("sign");
        return { success: false, message: "stop" };
    });
    await mountDialog({ requestID: 7, accessToken: "a/b" });
    await waitFor(".alert");
    expect.verifySteps(["sign"]);
});

test("a successful launch shows the waiting phase and opens the app link", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => ({ state: "pending" }));
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    expect(".modal-body").toHaveText(/Georgian ID Card.*should now open/s);
    expect(".modal-footer button:contains('Open the application again')").toHaveCount(1);
    expect(".modal-footer button:contains('Try again')").toHaveCount(0);
    expect(linkClicks).toEqual([launchUrl]);
    expect("a[href]").toHaveCount(0, { message: "the temporary link is removed" });
});

test("open the application again clicks the launch link once more", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => ({ state: "pending" }));
    await mountDialog();
    await waitFor(".modal-footer button:contains('Open the application again')");
    await click(".modal-footer button:contains('Open the application again')");
    expect(linkClicks).toEqual([launchUrl, launchUrl]);
});

test("status polling runs every 3000 ms and a signed state calls close then onSigned", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => {
        expect.step("status");
        return { state: "signed" };
    });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    await advanceTime(POLL_INTERVAL / 2);
    expect.verifySteps([]);
    await advanceTime(POLL_INTERVAL);
    await animationFrame();
    expect.verifySteps(["status", "close", "signed"]);
});

test("a pending status keeps polling", async () => {
    mockCancelAndLinks();
    mockLaunch();
    let calls = 0;
    onRpc(statusRoute, () => {
        calls++;
        return calls < 3 ? { state: "pending" } : { state: "signed" };
    });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    for (let i = 0; i < 3; i++) {
        await advanceTime(POLL_INTERVAL);
        await animationFrame();
    }
    expect(calls).toBe(3);
    expect.verifySteps(["close", "signed"]);
});

test("a failed status shows the fixed sentence and the retry button", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => ({ state: "failed", error: "Bad signature" }));
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    await advanceTime(POLL_INTERVAL);
    await waitFor(".alert");
    expect(".alert").toHaveText(FAILED_SENTENCE);
    expect(".alert").not.toHaveText("Bad signature");
    expect(".modal-footer button:contains('Try again')").toHaveCount(1);
    expect.verifySteps([]);
});

test("a failed status without a message shows the same sentence", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => ({ state: "failed" }));
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    await advanceTime(POLL_INTERVAL);
    await waitFor(".alert");
    expect(".alert").toHaveText(FAILED_SENTENCE);
});

test("a status rpc failure shows the status error", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => new Response("", { status: 502 }), { pure: true });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    await advanceTime(POLL_INTERVAL);
    await waitFor(".alert");
    expect(".alert").toHaveText("Could not check the signing status. Please try again.");
});

test("polling stops with a timeout error after the maximum number of polls", async () => {
    mockCancelAndLinks();
    mockLaunch();
    let calls = 0;
    onRpc(statusRoute, () => {
        calls++;
        return { state: "pending" };
    });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    for (let i = 0; i < MAX_POLLS; i++) {
        await advanceTime(POLL_INTERVAL);
    }
    await waitFor(".alert");
    expect(calls).toBe(MAX_POLLS);
    expect(".alert").toHaveText("Timed out waiting for the signature. Please try again.");
    expect(cancelCalls).toHaveLength(1);
});

test("a refused launch shows the server message", async () => {
    mockCancelAndLinks();
    mockLaunch({ success: false, message: "Some server reason" });
    await mountDialog();
    await waitFor(".alert");
    expect(".alert").toHaveText("Some server reason");
    expect(".modal-footer button:contains('Try again')").toHaveCount(1);
    expect(linkClicks).toEqual([]);
});

test("a refused launch without a message shows the default text", async () => {
    mockCancelAndLinks();
    mockLaunch({ success: false });
    await mountDialog();
    await waitFor(".alert");
    expect(".alert").toHaveText("Could not start Georgian ID Card signing.");
});

test("a server error shows its message", async () => {
    mockCancelAndLinks();
    onRpc(signRoute, () => {
        throw makeServerError({ message: "The signers before you have not signed yet." });
    });
    await mountDialog();
    await waitFor(".alert");
    expect(".alert").toHaveText("The signers before you have not signed yet.");
    expect(".modal").toHaveCount(1);
});

test("a network error shows the fallback text", async () => {
    mockCancelAndLinks();
    onRpc(signRoute, () => new Response("", { status: 502 }), { pure: true });
    await mountDialog();
    await waitFor(".alert");
    expect(".alert").toHaveText("Could not reach Odoo to start Georgian ID Card signing.");
});

test("try again posts to the sign route again", async () => {
    mockCancelAndLinks();
    let calls = 0;
    onRpc(signRoute, () => {
        calls++;
        return calls === 1
            ? { success: false, message: "First failure" }
            : { success: true, authorization_url: launchUrl };
    });
    onRpc(statusRoute, () => ({ state: "pending" }));
    await mountDialog();
    await waitFor(".alert");
    await click(".modal-footer button:contains('Try again')");
    await waitFor(".modal-body:contains('Waiting for the signature')");
    expect(calls).toBe(2);
    expect(".alert").toHaveCount(0);
    expect(linkClicks).toEqual([launchUrl]);
});

test("cancel calls the cancel route and closes the dialog", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => {
        expect.step("status");
        return { state: "pending" };
    });
    await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    await click(".modal-footer button:contains('Cancel')");
    await animationFrame();
    expect(cancelCalls).toEqual([cancelRoute]);
    expect.verifySteps(["close"]);
    await advanceTime(POLL_INTERVAL * 2);
    expect.verifySteps([]);
});

test("cancel while the launch rpc is pending closes the dialog", async () => {
    mockCancelAndLinks();
    mockLaunch({ success: false, message: "x" });
    await mountDialog();
    await waitFor(".modal-footer button:contains('Cancel')");
    await click(".modal-footer button:contains('Cancel')");
    await animationFrame();
    expect(cancelCalls).toEqual([cancelRoute]);
    expect.verifySteps(["close"]);
});

test("the dialog title and size come from dialogProps", async () => {
    mockCancelAndLinks();
    mockLaunch();
    onRpc(statusRoute, () => ({ state: "pending" }));
    const dialog = await mountDialog();
    await waitFor(".modal-body:contains('Waiting for the signature')");
    expect(".modal-title").toHaveText("Sign with Georgian ID Card");
    expect(dialog.dialogProps.size).toBe("md");
});

test("Document.getAuthDialog returns the Georgian ID Card dialog for geoeid", async () => {
    const fakeDocument = {
        authMethod: "geoeid",
        requestID,
        accessToken,
        signatureInfo: { signatureValues: signature, frameValues: frame },
    };
    const authDialog = await Document.prototype.getAuthDialog.call(fakeDocument);
    expect(authDialog.component).toBe(GeoeidSignerDialog);
    expect(authDialog.props.requestID).toBe(requestID);
    expect(authDialog.props.accessToken).toBe(accessToken);
    expect(authDialog.props.signatureValues).toBe(signature);
    expect(authDialog.props.frameValues).toBe(frame);
    expect(authDialog.props.onSigned).toBeInstanceOf(Function);
});

test("Document.getAuthDialog onSigned opens thank you dialog if last", async () => {
    const button = document.createElement("button");
    button.setAttribute("disabled", true);
    const fakeDocument = {
        authMethod: "geoeid",
        signatureInfo: {},
        validateButton: button,
        signInfo: { get: (key) => (key === "nameList" ? [] : false) },
        disableItems: () => expect.step("disableItems"),
        openThankYouDialog: () => expect.step("thankYou"),
        dialog: { add: () => expect.step("nextDirectSign") },
    };
    const { props } = await Document.prototype.getAuthDialog.call(fakeDocument);
    props.onSigned();
    expect(button).not.toHaveAttribute("disabled");
    expect.verifySteps(["disableItems", "thankYou"]);
});

test("Document.getAuthDialog onSigned opens next signer dialog if any", async () => {
    const fakeDocument = {
        authMethod: "geoeid",
        signatureInfo: {},
        validateButton: document.createElement("button"),
        signerName: "Current Signer",
        signInfo: {
            get: () => ["Next Signer"],
            set: (values) => {
                expect(values).toEqual({
                    lastSignedName: "Current Signer",
                    lastEmailedName: false,
                });
            },
        },
        disableItems: () => expect.step("disableItems"),
        openThankYouDialog: () => expect.step("thankYou"),
        dialog: { add: () => expect.step("nextDirectSign") },
    };
    const { props } = await Document.prototype.getAuthDialog.call(fakeDocument);
    props.onSigned();
    expect.verifySteps(["disableItems", "nextDirectSign"]);
});

test("Document.getAuthDialog onSigned acknowledges signers who were emailed", async () => {
    await makeTestApp();
    const fakeDocument = {
        authMethod: "geoeid",
        signatureInfo: {},
        validateButton: document.createElement("button"),
        signInfo: { get: (key) => key === "someSignersEmailed" },
        disableItems: () => expect.step("disableItems"),
        openThankYouDialog: () => expect.step("thankYou"),
        env: {
            services: {
                dialog: {
                    add: (component, props) => {
                        expect(props.body).toMatch(/All set!.*everyone has signed/);
                        expect.step("allSet");
                    },
                },
            },
        },
    };
    const { props } = await Document.prototype.getAuthDialog.call(fakeDocument);
    props.onSigned();
    expect.verifySteps(["disableItems", "allSet"]);
});

test("Document.getAuthDialog defers to core for other auth methods", async () => {
    const authDialog = await Document.prototype.getAuthDialog.call({
        authMethod: "",
        signatureInfo: {},
    });
    expect(authDialog).toBe(false);
});

test("public signing retries keep the attempt id and show their own failure", async () => {
    await makeTestApp();
    const attempts = [];
    onRpc(`/sign/geoeid/public/${requestID}/${accessToken}`, async (request) => {
        const { params } = await request.json();
        attempts.push(params.attempt_id);
        return false;
    });
    const button = document.createElement("button");
    const fakeDocument = {
        authMethod: "geoeid",
        isUnknownPublicUser: true,
        signatureInfo: { hasNoSignature: false },
        validateButton: button,
        signInfo: { get: (key) => (key === "documentId" ? requestID : accessToken) },
        dialog: { add: () => expect.step("failure") },
    };
    await Document.prototype._signDocuments.call(fakeDocument);
    await Document.prototype._signDocuments.call(fakeDocument);
    expect(attempts).toHaveLength(2);
    expect(attempts[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(attempts[1]).toBe(attempts[0]);
    expect(button).not.toHaveAttribute("disabled");
    expect.verifySteps(["failure", "failure"]);
});

test("SignablePDFIframe._geoeidNameImage returns a PNG data url", async () => {
    const url = SignablePDFIframe.prototype._geoeidNameImage.call({}, "Nino Beridze");
    expect(url).toMatch(/^data:image\/png;base64,/);
    const long = SignablePDFIframe.prototype._geoeidNameImage.call({}, "N".repeat(200));
    expect(long).toMatch(/^data:image\/png;base64,/);
});
