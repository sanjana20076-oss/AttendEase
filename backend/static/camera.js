/* The camera is bound to ONE server-authorized class, never a global latest class. */
(() => {
    "use strict";
    const video = document.getElementById("attendance-camera");
    const startButton = document.getElementById("start-attendance");
    const stopButton = document.getElementById("stop-attendance");
    const cameraStatus = document.getElementById("camera-status");
    const recognitionStatus = document.getElementById("recognition-status");
    const attendanceMessage = document.getElementById("attendance-message");
    const javascriptStatus = document.getElementById("javascript-status");
    const reviewStatus = document.getElementById("review-status");
    if (!video || !startButton || !stopButton || !cameraStatus || !recognitionStatus || !attendanceMessage) {
        if (javascriptStatus) javascriptStatus.textContent = "Attendance controls are missing from the page.";
        return;
    }
    const sessionId = Number(video.dataset.sessionId);
    if (!Number.isSafeInteger(sessionId) || sessionId <= 0) {
        cameraStatus.textContent = "No class selected. Return to the dashboard and select a class.";
        startButton.disabled = true;
        return;
    }
    const state = { stream: null, timer: null, request: null, generation: 0,
        starting: false, running: false, failures: 0 };
    const canvas = document.createElement("canvas");
    if (javascriptStatus) javascriptStatus.textContent = "Attendance controls loaded successfully.";

    function stopCamera(cameraText = "Camera is not running.", recognitionText = "Attendance scanning stopped.") {
        // Invalidates late getUserMedia, toBlob, and fetch results after Stop/restart.
        state.generation += 1;
        state.starting = false;
        state.running = false;
        clearTimeout(state.timer);
        state.timer = null;
        state.request?.abort();
        state.request = null;
        if (state.stream) state.stream.getTracks().forEach(track => track.stop());
        state.stream = null;
        video.srcObject = null;
        startButton.disabled = false;
        stopButton.disabled = true;
        cameraStatus.textContent = cameraText;
        recognitionStatus.textContent = recognitionText;
    }

    async function jsonRequest(url, options = {}) {
        const controller = new AbortController();
        state.request = controller;
        let timedOut = false;
        // Initial model initialization can take longer than subsequent frames.
        const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 120000);
        try {
            const response = await fetch(url, { ...options, signal: controller.signal,
                credentials: "same-origin", cache: "no-store" });
            if (!response.headers.get("content-type")?.includes("application/json")) {
                throw new Error(`Server returned a non-JSON response (${response.status}). Reload and check login/server logs.`);
            }
            return { response, data: await response.json() };
        } catch (error) {
            if (timedOut) throw new Error("Recognition timed out. Check model setup and the server log, then try again.");
            throw error;
        } finally {
            clearTimeout(timeout);
            if (state.request === controller) state.request = null;
        }
    }

    async function startAttendance() {
        if (state.starting || state.running) return;
        const generation = ++state.generation;
        state.starting = true;
        state.failures = 0;
        startButton.disabled = true;
        stopButton.disabled = false;  // Stop also cancels startup.
        attendanceMessage.textContent = "";
        if (reviewStatus) reviewStatus.textContent = "";
        cameraStatus.textContent = "Checking the selected class session...";
        recognitionStatus.textContent = "Preparing automatic attendance...";
        try {
            if (!navigator.mediaDevices?.getUserMedia) {
                throw new Error("Camera access requires localhost or HTTPS and a supported browser. Open the app in its own browser tab if an embedded preview blocks it.");
            }
            const sessionUrl = new URL(video.dataset.sessionUrl, window.location.href);
            sessionUrl.searchParams.set("session_id", String(sessionId));
            const { response, data } = await jsonRequest(sessionUrl);
            if (generation !== state.generation) return;
            if (!response.ok || !data.active || Number(data.session_id) !== sessionId) {
                throw new Error(data.error || data.message || "The selected class is not active. Return to the dashboard.");
            }
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, audio: false
            });
            if (generation !== state.generation) {
                stream.getTracks().forEach(track => track.stop());
                return;
            }
            state.stream = stream;
            video.srcObject = stream;
            await video.play();
            if (generation !== state.generation) return;
            state.running = true;
            state.starting = false;
            stream.getVideoTracks().forEach(track => track.addEventListener("ended", () => {
                if (generation === state.generation) stopCamera("Camera disconnected.", "Reconnect the camera and start again.");
            }));
            cameraStatus.textContent = `Camera running for ${data.subject_name}, section ${data.section} (session ${sessionId}).`;
            recognitionStatus.textContent = "Looking for one registered face...";
            // Sequential completion-based scheduling prevents overlapping inference requests.
            void recognizeFrame(generation);
        } catch (error) {
            if (generation !== state.generation) return;
            const messages = {
                NotAllowedError: "Camera permission denied. Allow camera access in browser settings (and open a separate tab if this preview blocks it).",
                NotFoundError: "No camera was found on this device.",
                NotReadableError: "Camera is busy. Close other apps using it and try again."
            };
            stopCamera(messages[error.name] || error.message || "Could not start the camera.", "Attendance has not started.");
        } finally {
            if (generation === state.generation) {
                state.starting = false;
                startButton.disabled = state.running;
                stopButton.disabled = !state.running;
            }
        }
    }

    async function recognizeFrame(generation) {
        if (generation !== state.generation || !state.running) return;
        try {
            if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
            const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
            canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.85));
            if (generation !== state.generation || !state.running) return;
            if (!blob) throw new Error("Could not capture a camera frame.");
            const formData = new FormData();
            formData.append("frame", blob, "camera.jpg");
            formData.append("session_id", String(sessionId));
            const { response, data } = await jsonRequest(video.dataset.recognizeUrl, {
                method: "POST", body: formData,
                headers: { "X-CSRF-Token": video.dataset.csrfToken }
            });
            if (generation !== state.generation || !state.running) return;
            if (!response.ok) {
                stopCamera("Camera stopped.", data.error || data.message || `Recognition failed (${response.status}).`);
                return; // Includes expired login, ended class, and missing model: no endless retry.
            }
            state.failures = 0;
            if (data.student_id !== null && data.student_id !== undefined) {
                const name = data.student_name || `Student ${data.student_id}`;
                const roll = data.roll_number ? ` (${data.roll_number})` : "";
                const score = Number(data.similarity).toFixed(3);
                recognitionStatus.textContent = `${name}${roll} · Similarity ${score}`;
                attendanceMessage.textContent = data.attendance_message || "Attendance status unavailable.";
                if (reviewStatus) {
                    reviewStatus.textContent = !data.attendance_recorded ? "No attendance approval."
                        : data.review_status === "auto_approved" ? "Present · Review successful (automatic)."
                        : data.review_status === "confirmed" ? "Present · Confirmed by faculty."
                        : "Present · Pending faculty review.";
                }
            } else {
                recognitionStatus.textContent = data.message || "No matching registered student found.";
                attendanceMessage.textContent = "";
                if (reviewStatus) reviewStatus.textContent = "";
            }
        } catch (error) {
            if (generation !== state.generation || !state.running) return;
            state.failures += 1;
            if (state.failures >= 3) {
                stopCamera("Camera stopped after repeated connection failures.", error.message || "Check the server and start again.");
                return;
            }
            recognitionStatus.textContent = `Connection problem; retrying (${state.failures}/3). ${error.message || ""}`;
        } finally {
            if (generation === state.generation && state.running) {
                state.timer = setTimeout(() => { void recognizeFrame(generation); }, 2000);
            }
        }
    }

    startButton.addEventListener("click", () => { void startAttendance(); });
    stopButton.addEventListener("click", () => stopCamera());
    window.addEventListener("pagehide", () => stopCamera());
    document.addEventListener("visibilitychange", () => {
        if (document.hidden && (state.running || state.starting)) {
            stopCamera("Camera paused while the tab is hidden.", "Click Start Attendance to resume.");
        }
    });
})();
