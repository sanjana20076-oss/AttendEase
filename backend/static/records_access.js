/* Server-side guards are authoritative; this also hides stale/back-cached views. */
(() => {
    "use strict";
    const content = document.getElementById("protected-attendance-records");
    if (!content?.dataset.accessStatusUrl || !content.dataset.verificationUrl) return;
    let timer = null;
    let checking = false;
    let locked = false;
    function lockView() {
        if (locked) return;
        locked = true;
        content.hidden = true;
        clearTimeout(timer);
        window.location.replace(content.dataset.verificationUrl);
    }
    function armTimer(milliseconds) {
        clearTimeout(timer);
        if (!Number.isFinite(milliseconds) || milliseconds <= 0) { lockView(); return; }
        timer = setTimeout(lockView, milliseconds);
    }
    async function verifyAccess() {
        if (locked || checking) return;
        checking = true;
        content.hidden = true;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(content.dataset.accessStatusUrl, {
                credentials: "same-origin", cache: "no-store", signal: controller.signal
            });
            if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) { lockView(); return; }
            const result = await response.json();
            if (!result.verified || Number(result.remaining_seconds) <= 0) { lockView(); return; }
            armTimer(Number(result.remaining_seconds) * 1000);
            if (!locked) content.hidden = document.hidden;
        } catch (_) { lockView(); }
        finally { clearTimeout(timeout); checking = false; }
    }
    armTimer(Number(content.dataset.expiresInMs));
    void verifyAccess();
    window.addEventListener("pagehide", () => { content.hidden = true; });
    window.addEventListener("pageshow", () => { void verifyAccess(); });
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) content.hidden = true;
        else void verifyAccess();
    });
})();
