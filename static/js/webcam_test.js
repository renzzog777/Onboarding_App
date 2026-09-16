(function () {
    const video = document.getElementById("preview");
    const canvas = document.getElementById("captureCanvas");
    const captureBtn = document.getElementById("captureBtn");
    const snapshotPreview = document.getElementById("snapshotPreview");
    const finishBtn = document.getElementById("finishBtn");
    const deviceInfo = document.getElementById("deviceInfo");

    let deviceLabel = "Unknown";
    let resolution = "Unknown";
    let snapshotDataUrl = null;
    let stream = null;

    async function start() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = stream;
            const track = stream.getVideoTracks()[0];
            const settings = track.getSettings ? track.getSettings() : {};
            deviceLabel = track.label || "Unknown camera";
            if (settings.width && settings.height) {
                resolution = `${settings.width}x${settings.height}`;
            }
            deviceInfo.textContent = `Camera: ${deviceLabel} (${resolution})`;
        } catch (err) {
            deviceInfo.textContent = "Camera access was blocked or unavailable.";
        }
    }
    start();

    captureBtn.addEventListener("click", () => {
        if (!video.videoWidth) {
            alert("Camera feed not ready yet.");
            return;
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        snapshotDataUrl = canvas.toDataURL("image/jpeg", 0.8);
        snapshotPreview.src = snapshotDataUrl;
        snapshotPreview.style.display = "block";
    });

    finishBtn.addEventListener("click", async () => {
        const skipReason = document.getElementById("skipReasonInput").value.trim();
        const captureError = document.getElementById("captureError");
        if (!snapshotDataUrl && !skipReason) {
            captureError.style.display = "block";
            return;
        }
        captureError.style.display = "none";

        finishBtn.disabled = true;
        finishBtn.textContent = "Generating report...";
        try {
            const payload = {
                device_label: deviceLabel,
                resolution: resolution,
                image_clear: document.getElementById("clearConfirm").checked,
                snapshot: snapshotDataUrl,
                capture_skipped_reason: snapshotDataUrl ? null : skipReason,
            };
            const result = await saveTestResult("webcam", window.SESSION_ID, payload);
            if (stream) stream.getTracks().forEach((t) => t.stop());
            window.location.href = result.next_url;
        } catch (err) {
            alert("Could not save webcam test result: " + err.message);
            finishBtn.disabled = false;
            finishBtn.textContent = "Finish Test & Generate Report";
        }
    });
})();
