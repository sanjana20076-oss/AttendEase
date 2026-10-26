
const video = document.getElementById("faceVideo");
const canvas = document.getElementById("faceCanvas");
const startButton = document.getElementById("startCameraBtn");
const captureButton = document.getElementById("captureFaceBtn");
const stopButton = document.getElementById("stopCameraBtn");
const status = document.getElementById("cameraStatus");
const preview = document.getElementById("capturedFace");
const faceInput = document.getElementById("face_image");
const form = document.getElementById("studentForm");

let cameraStream = null;

startButton.addEventListener("click", async () => {
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user" },
            audio: false
        });

        video.srcObject = cameraStream;
        await video.play();

        startButton.disabled = true;
        captureButton.disabled = false;
        stopButton.disabled = false;

        status.textContent = "Webcam started. Position one face in the frame.";
    } catch (error) {
        console.error("Camera error:", error);
        status.textContent =
            "Could not access webcam. Allow camera permission and try again.";
    }
});

captureButton.addEventListener("click", () => {
    if (!cameraStream || !video.videoWidth || !video.videoHeight) {
        status.textContent = "Start the webcam and wait for the video first.";
        return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = canvas.toDataURL("image/jpeg", 0.9);
    faceInput.value = imageData;

    preview.src = imageData;
    preview.style.display = "block";

    status.textContent =
        "Face captured. Review the preview before registering the student.";
});

stopButton.addEventListener("click", stopCamera);

function stopCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }

    video.srcObject = null;
    startButton.disabled = false;
    captureButton.disabled = true;
    stopButton.disabled = true;

    status.textContent = "Webcam stopped.";
}

form.addEventListener("submit", (event) => {
    if (!faceInput.value) {
        event.preventDefault();
        status.textContent = "Please capture the student's face first.";
        return;
    }

    stopCamera();
});

window.addEventListener("beforeunload", stopCamera);
