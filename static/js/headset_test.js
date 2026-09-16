(function () {
    const continueBtn = document.getElementById("continueBtn");
    const deviceInfo = document.getElementById("deviceInfo");
    const meterBar = document.getElementById("meterBar");

    let micDetected = false;
    let peakLevel = 0;
    let outputDeviceLabel = "Unknown";
    let inputDeviceLabel = "Unknown";
    let micStream = null;

    function playTone(pan) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const panner = ctx.createStereoPanner();
        const gain = ctx.createGain();
        osc.frequency.value = 440;
        panner.pan.value = pan;
        gain.gain.value = 0.25;
        osc.connect(gain).connect(panner).connect(ctx.destination);
        osc.start();
        setTimeout(() => {
            osc.stop();
            ctx.close();
        }, 800);
    }

    document.getElementById("playLeft").addEventListener("click", () => playTone(-1));
    document.getElementById("playRight").addEventListener("click", () => playTone(1));

    async function refreshDeviceLabels() {
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const outputs = devices.filter((d) => d.kind === "audiooutput");
            const inputs = devices.filter((d) => d.kind === "audioinput");
            if (outputs[0]) outputDeviceLabel = outputs[0].label || "Default output";
            if (inputs[0]) inputDeviceLabel = inputs[0].label || "Default input";
            deviceInfo.textContent = `Output: ${outputDeviceLabel} | Input: ${inputDeviceLabel}`;
        } catch (err) {
            deviceInfo.textContent = "Could not list audio devices.";
        }
    }
    refreshDeviceLabels();

    document.getElementById("startMic").addEventListener("click", async () => {
        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            await refreshDeviceLabels();
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const ctx = new AudioCtx();
            const source = ctx.createMediaStreamSource(micStream);
            const analyser = ctx.createAnalyser();
            analyser.fftSize = 512;
            source.connect(analyser);
            const data = new Uint8Array(analyser.frequencyBinCount);

            function tick() {
                analyser.getByteFrequencyData(data);
                const avg = data.reduce((a, b) => a + b, 0) / data.length;
                const pct = Math.min(100, Math.round((avg / 128) * 100));
                meterBar.style.width = pct + "%";
                if (pct > peakLevel) peakLevel = pct;
                if (pct > 8) micDetected = true;
                requestAnimationFrame(tick);
            }
            tick();
        } catch (err) {
            deviceInfo.textContent = "Microphone access was blocked or unavailable.";
        }
    });

    /* ---------- Voice recording (count 1 to 10) ---------- */
    let mediaRecorder = null;
    let recordedChunks = [];
    let recordingDataUrl = null;
    const startRecordingBtn = document.getElementById("startRecording");
    const stopRecordingBtn = document.getElementById("stopRecording");
    const recordingStatus = document.getElementById("recordingStatus");
    const recordingPlayback = document.getElementById("recordingPlayback");
    const recordingError = document.getElementById("recordingError");

    startRecordingBtn.addEventListener("click", async () => {
        try {
            if (!micStream) {
                micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                await refreshDeviceLabels();
            }
            recordedChunks = [];
            // Let the browser pick its own supported format (Chrome
            // defaults to webm, Safari to mp4) rather than forcing one
            // that might not be supported.
            mediaRecorder = new MediaRecorder(micStream);
            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) recordedChunks.push(e.data);
            };
            mediaRecorder.onstop = () => {
                const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
                const reader = new FileReader();
                reader.onloadend = () => {
                    recordingDataUrl = reader.result;
                    recordingPlayback.src = recordingDataUrl;
                    recordingPlayback.style.display = "block";
                    recordingError.style.display = "none";
                };
                reader.readAsDataURL(blob);
                recordingStatus.textContent = "Recording saved - you can play it back above, or record again to replace it.";
            };
            mediaRecorder.start();
            recordingStatus.textContent = "Recording... count out loud from 1 to 10, then click Stop.";
            startRecordingBtn.disabled = true;
            stopRecordingBtn.disabled = false;
        } catch (err) {
            recordingStatus.textContent = "Microphone access was blocked or unavailable.";
        }
    });

    stopRecordingBtn.addEventListener("click", () => {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        startRecordingBtn.disabled = false;
        stopRecordingBtn.disabled = true;
    });

    continueBtn.addEventListener("click", async () => {
        if (!recordingDataUrl) {
            recordingError.style.display = "block";
            return;
        }
        recordingError.style.display = "none";

        continueBtn.disabled = true;
        continueBtn.textContent = "Saving...";
        try {
            const payload = {
                output_device: outputDeviceLabel,
                input_device: inputDeviceLabel,
                left_ear_confirmed: document.getElementById("leftConfirm").checked,
                right_ear_confirmed: document.getElementById("rightConfirm").checked,
                mic_detected: micDetected,
                mic_peak_level: peakLevel,
                mic_visually_confirmed: document.getElementById("micConfirm").checked,
                recording: recordingDataUrl,
            };
            const result = await saveTestResult("headset", window.SESSION_ID, payload);
            if (micStream) micStream.getTracks().forEach((t) => t.stop());
            window.location.href = result.next_url;
        } catch (err) {
            alert("Could not save headset test result: " + err.message);
            continueBtn.disabled = false;
            continueBtn.textContent = "Continue to Webcam Test";
        }
    });
})();
