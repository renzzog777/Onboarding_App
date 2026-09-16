(function () {
    const waitingIndicator = document.getElementById("waitingIndicator");
    const detectedMsg = document.getElementById("detectedMsg");
    const copyBtn = document.getElementById("copyBtn");
    const commandBlock = document.getElementById("commandBlock");
    const manualSelect = document.getElementById("manualSelect");
    const manualBtn = document.getElementById("manualBtn");
    const manualError = document.getElementById("manualError");

    let stopped = false;

    copyBtn.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(commandBlock.textContent.trim());
            copyBtn.textContent = "Copied!";
            setTimeout(() => { copyBtn.textContent = "Copy Command"; }, 1500);
        } catch (err) {
            alert("Could not copy automatically - select the text manually instead.");
        }
    });

    function goToMouseTest() {
        window.location.href = `/test/mouse/${window.SESSION_ID}`;
    }

    async function poll() {
        if (stopped) return;
        try {
            const res = await fetch(`/api/network-status/${window.SESSION_ID}`);
            const data = await res.json();
            if (data.detected) {
                stopped = true;
                waitingIndicator.style.display = "none";
                detectedMsg.style.display = "block";
                detectedMsg.textContent = `Detected: ${data.network_type}. Continuing...`;
                setTimeout(goToMouseTest, 900);
                return;
            }
        } catch (err) {
            // network hiccup - just try again on the next tick
        }
        setTimeout(poll, 2000);
    }
    poll();

    manualBtn.addEventListener("click", async () => {
        const value = manualSelect.value;
        if (!value) {
            manualError.style.display = "block";
            return;
        }
        manualError.style.display = "none";
        stopped = true;
        manualBtn.disabled = true;
        manualBtn.textContent = "Saving...";
        try {
            const res = await fetch(`/api/set-network-manual/${window.SESSION_ID}`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: `network_type=${encodeURIComponent(value)}`,
            });
            if (!res.ok) throw new Error("Request failed");
            goToMouseTest();
        } catch (err) {
            alert("Could not save your selection: " + err.message);
            manualBtn.disabled = false;
            manualBtn.textContent = "Continue with manual selection";
            stopped = false;
            poll();
        }
    });
})();
