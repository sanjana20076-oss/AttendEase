(() => {
    "use strict";
    const video = document.getElementById("faculty-login-camera");
    const canvas = document.getElementById("faculty-login-canvas");
    const form = document.getElementById("faculty-login-form");
    const imageInput = document.getElementById("faculty-login-image");
    const startButton = document.getElementById("faculty-login-start");
    const stopButton = document.getElementById("faculty-login-stop");
    const submitButton = document.getElementById("faculty-login-submit");
    const status = document.getElementById("faculty-login-status");
    let stream = null;
    let generation = 0;
    function stopCamera() {
        generation += 1;
        if (stream) stream.getTracks().forEach(track => track.stop());
        stream = null;
        video.srcObject = null;
        startButton.disabled = false;
        stopButton.disabled = true;
        submitButton.disabled = true;
    }
    startButton.addEventListener("click", async () => {
        if (startButton.disabled) return;
        const run = ++generation;
        startButton.disabled = true;
        stopButton.disabled = false;
        try {
            if (!navigator.mediaDevices?.getUserMedia) {
                throw new Error("Camera access requires localhost or HTTPS. Open this page in its own tab if an embedded preview blocks permissions.");
            }
            const opened = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false
            });
            if (run !== generation) { opened.getTracks().forEach(track => track.stop()); return; }
            stream = opened;
            video.srcObject = stream;
            await video.play();
            if (run !== generation) return;
            submitButton.disabled = false;
            status.textContent = "Camera ready. Position one registered faculty face clearly.";
        } catch (error) {
            if (run !== generation) return;
            stopCamera();
            status.textContent = error.name === "NotAllowedError"
                ? "Camera permission denied. Allow it in browser settings, or open the app in its own tab."
                : error.message || "Cannot access camera.";
        }
    });
    stopButton.addEventListener("click", () => { stopCamera(); status.textContent = "Camera stopped."; });
    form.addEventListener("submit", event => {
        event.preventDefault();
        if (!stream || !video.videoWidth || !video.videoHeight) {
            status.textContent = "Start the camera and wait for the video.";
            return;
        }
        try {
            const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
            imageInput.value = canvas.toDataURL("image/jpeg", 0.85);
            stopCamera();
            status.textContent = "Checking your face. The first model load may take longer...";
            submitButton.disabled = true;
            form.submit();
        } catch (error) {
            status.textContent = "Unable to capture a frame. Start the camera and try again.";
        }
    });
    window.addEventListener("pagehide", stopCamera);
})();
