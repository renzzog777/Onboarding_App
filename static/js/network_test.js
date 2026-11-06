// Network test: measures speed, latency, jitter and responsiveness in the
// browser against Cloudflare's public speed-test servers (they allow
// cross-origin requests). Terminal is restricted on advisor Macs, so
// macOS's networkQuality can't be used; the metrics here mirror it.
(function () {
    const CF = "https://speed.cloudflare.com";
    const PHASE_MS = 8000;          // length of each download/upload phase
    const WARMUP_MS = 1500;         // ignored at the start of each phase (TCP ramp-up)
    const MAX_PHASE_BYTES = 400e6;  // safety cap on fast connections
    const STREAMS = 4;              // parallel connections, like networkQuality
    const DOWN_CHUNK = 25e6;
    const UP_CHUNK = 2e6;
    const IDLE_SAMPLES = 20;
    const T = window.NETWORK_THRESHOLDS;

    const runBtn = document.getElementById("runBtn");
    const finishBtn = document.getElementById("finishBtn");
    const progress = document.getElementById("progress");
    const progressText = document.getElementById("progressText");
    const runError = document.getElementById("runError");
    const finishError = document.getElementById("finishError");
    const resultsWrap = document.getElementById("resultsWrap");

    let results = null;
    let running = false;

    // ---------- helpers ----------
    const median = (a) => {
        if (!a.length) return null;
        const s = [...a].sort((x, y) => x - y);
        const m = Math.floor(s.length / 2);
        return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
    };
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    function responsivenessLabel(rpm) {
        if (rpm == null) return null;
        if (rpm >= 1000) return "High";
        if (rpm >= 200) return "Medium";
        return "Low";
    }

    // Cloudflare reports its own processing time; subtract it so only
    // network round-trip time is left.
    function serverMs(res) {
        const st = res.headers.get("server-timing") || "";
        const m = st.match(/cfSpeedWorker;dur=([\d.]+)/);
        return m ? parseFloat(m[1]) : 0;
    }

    async function latencyProbe() {
        const t0 = performance.now();
        const res = await fetch(`${CF}/__down?bytes=0&r=${Math.random()}`, { cache: "no-store" });
        await res.arrayBuffer();
        return Math.max(performance.now() - t0 - serverMs(res), 0.1);
    }

    // Runs latency probes back-to-back until stop() - used while the line
    // is loaded, to measure responsiveness (latency under working conditions).
    function startLoadedProbes(samples) {
        let stopped = false;
        (async () => {
            while (!stopped) {
                try { samples.push(await latencyProbe()); } catch (e) { /* ignore */ }
                await sleep(200);
            }
        })();
        return () => { stopped = true; };
    }

    // Tracks bytes over time and returns Mbps measured after the warm-up.
    function makeMeter() {
        const start = performance.now();
        let total = 0, warmBytes = null, warmTime = null;
        return {
            add(n) {
                total += n;
                const now = performance.now();
                if (warmBytes === null && now - start >= WARMUP_MS) {
                    warmBytes = total; warmTime = now;
                }
            },
            total: () => total,
            elapsed: () => performance.now() - start,
            mbps() {
                const now = performance.now();
                if (warmBytes === null || now - warmTime < 500) {
                    return (total * 8) / ((now - start) / 1000) / 1e6;
                }
                return ((total - warmBytes) * 8) / ((now - warmTime) / 1000) / 1e6;
            },
        };
    }

    // ---------- phases ----------
    async function measureIdle() {
        await latencyProbe(); // open + warm the connection
        await latencyProbe();
        const s = [];
        for (let i = 0; i < IDLE_SAMPLES; i++) {
            s.push(await latencyProbe());
            progressText.textContent = `Measuring idle latency... (${i + 1}/${IDLE_SAMPLES})`;
        }
        let diffs = 0;
        for (let i = 1; i < s.length; i++) diffs += Math.abs(s[i] - s[i - 1]);
        return { idle: median(s), jitter: diffs / (s.length - 1) };
    }

    async function measureDownload(loadedSamples) {
        const meter = makeMeter();
        const ctrl = new AbortController();
        const done = () => meter.elapsed() >= PHASE_MS || meter.total() >= MAX_PHASE_BYTES;
        const stopProbes = startLoadedProbes(loadedSamples);
        const ticker = setInterval(() => {
            progressText.textContent = `Measuring download... ${meter.mbps().toFixed(1)} Mbps`;
            if (done()) ctrl.abort();
        }, 250);

        async function stream() {
            while (!done()) {
                const res = await fetch(`${CF}/__down?bytes=${DOWN_CHUNK}&r=${Math.random()}`, {
                    cache: "no-store", signal: ctrl.signal,
                });
                const reader = res.body.getReader();
                while (true) {
                    const { done: end, value } = await reader.read();
                    if (end) break;
                    meter.add(value.length);
                }
            }
        }
        try {
            await Promise.all(Array.from({ length: STREAMS }, stream));
        } catch (e) {
            if (e.name !== "AbortError") throw e;
        } finally {
            clearInterval(ticker);
            stopProbes();
            ctrl.abort(); // stop any streams still running after an error
        }
        return meter.mbps();
    }

    function measureUpload(loadedSamples) {
        return new Promise((resolve, reject) => {
            const meter = makeMeter();
            const payload = new Blob([new Uint8Array(UP_CHUNK)]);
            const active = new Set();
            const stopProbes = startLoadedProbes(loadedSamples);
            let finished = false;

            const finish = (err) => {
                if (finished) return;
                finished = true;
                clearInterval(ticker);
                stopProbes();
                active.forEach((x) => x.abort());
                if (err) reject(err); else resolve(meter.mbps());
            };
            const done = () => meter.elapsed() >= PHASE_MS || meter.total() >= MAX_PHASE_BYTES;

            function send() {
                if (finished || done()) return;
                const xhr = new XMLHttpRequest();
                let sent = 0;
                xhr.open("POST", `${CF}/__up?r=${Math.random()}`);
                xhr.upload.onprogress = (e) => { meter.add(e.loaded - sent); sent = e.loaded; };
                xhr.onload = () => { active.delete(xhr); send(); };
                xhr.onerror = () => { active.delete(xhr); finish(new Error("Upload request failed")); };
                active.add(xhr);
                xhr.send(payload);
            }
            const ticker = setInterval(() => {
                progressText.textContent = `Measuring upload... ${meter.mbps().toFixed(1)} Mbps`;
                if (done()) finish();
            }, 250);
            for (let i = 0; i < STREAMS; i++) send();
        });
    }

    async function checkWarp() {
        try {
            const res = await fetch("https://1.1.1.1/cdn-cgi/trace", { cache: "no-store" });
            const text = await res.text();
            const get = (k) => (text.match(new RegExp(`^${k}=(.*)$`, "m")) || [])[1] || null;
            return { warp: get("warp"), zt_gateway: get("gateway") };
        } catch (e) {
            return { warp: null, zt_gateway: null };
        }
    }

    // ---------- UI ----------
    function setCell(id, text) { document.getElementById(id).textContent = text; }
    function setStatus(id, ok) {
        const el = document.getElementById(id);
        el.innerHTML = `<span class="status-pill ${ok ? "PASS" : "FAIL"}">${ok ? "PASS" : "FAIL"}</span>`;
    }

    function render(r) {
        resultsWrap.style.display = "block";
        setCell("rDown", `${r.download_mbps.toFixed(1)} Mbps`);
        setCell("rUp", `${r.upload_mbps.toFixed(1)} Mbps`);
        setCell("rIdle", `${r.idle_latency_ms.toFixed(0)} ms`);
        setCell("rResp", r.rpm != null ? `${r.responsiveness} (${r.rpm.toFixed(0)} RPM)` : "Not measured");
        setCell("rJitter", `${r.jitter_ms.toFixed(1)} ms`);
        setCell("rLoaded", r.loaded_latency_ms != null ? `${r.loaded_latency_ms.toFixed(0)} ms` : "Not measured");
        setCell("rWarp", { on: "On", plus: "On (WARP+)", off: "Off" }[r.warp] || "Unknown");
        const order = ["Low", "Medium", "High"];
        setStatus("sDown", r.download_mbps >= T.min_download_mbps);
        setStatus("sUp", r.upload_mbps >= T.min_upload_mbps);
        setStatus("sIdle", r.idle_latency_ms <= T.max_idle_latency_ms);
        setStatus("sResp", r.responsiveness != null &&
            order.indexOf(r.responsiveness) >= order.indexOf(T.min_responsiveness));
    }

    runBtn.addEventListener("click", async () => {
        if (running) return;
        running = true;
        runBtn.disabled = true;
        finishBtn.disabled = true;
        runError.style.display = "none";
        progress.style.display = "flex";
        try {
            progressText.textContent = "Measuring idle latency...";
            const { idle, jitter } = await measureIdle();
            const loaded = [];
            const download = await measureDownload(loaded);
            const upload = await measureUpload(loaded);
            progressText.textContent = "Checking for VPN...";
            const warp = await checkWarp();
            const loadedMs = median(loaded);
            const rpm = loadedMs ? 60000 / loadedMs : null;
            results = {
                download_mbps: Math.round(download * 10) / 10,
                upload_mbps: Math.round(upload * 10) / 10,
                idle_latency_ms: Math.round(idle * 10) / 10,
                jitter_ms: Math.round(jitter * 10) / 10,
                loaded_latency_ms: loadedMs != null ? Math.round(loadedMs * 10) / 10 : null,
                rpm: rpm != null ? Math.round(rpm) : null,
                responsiveness: responsivenessLabel(rpm),
                warp: warp.warp,
                zt_gateway: warp.zt_gateway,
                measured_at: new Date().toISOString(),
                user_agent: navigator.userAgent,
            };
            render(results);
            runBtn.textContent = "Run Test Again";
        } catch (err) {
            runError.textContent = "The speed test couldn't finish: " + err.message +
                ". Check the internet connection and try again. If speed-test sites are blocked, explain below.";
            runError.style.display = "block";
        } finally {
            progress.style.display = "none";
            runBtn.disabled = false;
            finishBtn.disabled = false;
            running = false;
        }
    });

    finishBtn.addEventListener("click", async () => {
        const connectionPath = document.getElementById("connectionPath").value;
        const skipReason = document.getElementById("skipReasonInput").value.trim();
        finishError.style.display = "none";
        if (!connectionPath) {
            finishError.textContent = "Please answer how this Mac is connected to the internet.";
            finishError.style.display = "block";
            return;
        }
        if (!results && !skipReason) {
            finishError.textContent = "Run the network test, or explain why it couldn't be run.";
            finishError.style.display = "block";
            return;
        }
        finishBtn.disabled = true;
        runBtn.disabled = true;
        finishBtn.textContent = "Generating report...";
        try {
            const payload = Object.assign({}, results || {}, {
                connection_path: connectionPath,
                test_skipped_reason: results ? null : skipReason,
            });
            const result = await saveTestResult("network", window.SESSION_ID, payload);
            window.location.href = result.next_url;
        } catch (err) {
            alert("Could not save network test result: " + err.message);
            finishBtn.disabled = false;
            runBtn.disabled = false;
            finishBtn.textContent = "Finish Test & Generate Report";
        }
    });
})();
