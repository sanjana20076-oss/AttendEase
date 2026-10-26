
const video = document.getElementById("faculty-camera");
const canvas = document.getElementById("faculty-canvas");

const startButton = document.getElementById("start-faculty-camera");
const captureButton = document.getElementById("capture-faculty-face");
const retakeButton = document.getElementById("retake-faculty-face");

const status = document.getElementById("faculty-camera-status");
const previewContainer = document.getElementById("faculty-preview-container");
const preview = document.getElementById("faculty-face-preview");
const faceImageInput = document.getElementById("faculty-face-image");
const registerButton = document.getElementById("register-faculty");
const form = document.querySelector("form");

let cameraStream = null;

async function startCamera() {
    try {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
        }

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: false
        });

        video.srcObject = cameraStream;
        await video.play();

        video.hidden = false;
        previewContainer.hidden = true;

        faceImageInput.value = "";
        captureButton.disabled = false;
        retakeButton.disabled = true;
        registerButton.disabled = true;

        status.textContent = "Camera ready. Position your face clearly.";
    } catch (error) {
        console.error("Camera error:", error);
        status.textContent =
            "Unable to access the camera. Allow camera permission and try again.";
    }
}

function stopCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => {
            track.stop();
        });

        cameraStream = null;
    }

    video.pause();
    video.srcObject = null;
    video.hidden = true;

    captureButton.disabled = true;
    startButton.disabled = false;

    status.textContent = "Camera stopped.";
}


function captureFace() {
    if (!video.videoWidth || !video.videoHeight) {
        status.textContent = "Camera is not ready. Try again.";
        return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = canvas.toDataURL("image/jpeg", 0.9);

    faceImageInput.value = imageData;
    preview.src = imageData;

    video.hidden = true;
    previewContainer.hidden = false;

    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }

    captureButton.disabled = true;
    retakeButton.disabled = false;
    registerButton.disabled = false;

    status.textContent =
        "Photo captured. Review it before registering the faculty member.";
}

function retakeFace() {
    faceImageInput.value = "";
    preview.src = "";
    previewContainer.hidden = true;
    startCamera();
}


const stopButton = document.getElementById("stop-faculty-camera");

startButton.addEventListener("click", startCamera);
stopButton.addEventListener("click", stopCamera);
captureButton.addEventListener("click", captureFace);
retakeButton.addEventListener("click", retakeFace);


form.addEventListener("submit", function (event) {
    if (!faceImageInput.value) {
        event.preventDefault();
        status.textContent = "Capture a faculty face photo before registering.";
    }
});

window.addEventListener("pagehide", function () {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
    }
});

captureButton.disabled = true;
retakeButton.disabled = true;
registerButton.disabled = true;
previewContainer.hidden = true;
