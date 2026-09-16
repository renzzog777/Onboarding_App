(function () {
    const zone = document.getElementById("mouseZone");
    const boxes = {};
    document.querySelectorAll(".button-box").forEach((el) => {
        boxes[el.dataset.key] = el;
    });
    const warning = document.getElementById("doubleClickWarning");
    const continueBtn = document.getElementById("continueBtn");

    const state = {
        left: false,
        right: false,
        middle: false,
        scroll_up: false,
        scroll_down: false,
    };
    let doubleClickDetected = false;
    const lastClickTime = {};
    const DOUBLE_CLICK_THRESHOLD_MS = 60; // humanly-impossible repeat click

    function mark(key) {
        if (!(key in state)) return;
        state[key] = true;
        if (boxes[key]) boxes[key].classList.add("detected");
    }

    function checkDoubleClick(key) {
        const now = performance.now();
        if (lastClickTime[key] !== undefined) {
            const delta = now - lastClickTime[key];
            if (delta > 0 && delta < DOUBLE_CLICK_THRESHOLD_MS) {
                doubleClickDetected = true;
                warning.style.display = "block";
            }
        }
        lastClickTime[key] = now;
    }

    zone.addEventListener("contextmenu", (e) => e.preventDefault());

    zone.addEventListener("mousedown", (e) => {
        e.preventDefault();
        let key = null;
        if (e.button === 0) key = "left";
        else if (e.button === 1) key = "middle";
        else if (e.button === 2) key = "right";
        if (key) {
            checkDoubleClick(key);
            mark(key);
        }
    });

    zone.addEventListener("wheel", (e) => {
        e.preventDefault();
        if (e.deltaY < 0) mark("scroll_up");
        else if (e.deltaY > 0) mark("scroll_down");
    }, { passive: false });

    continueBtn.addEventListener("click", async () => {
        continueBtn.disabled = true;
        continueBtn.textContent = "Saving...";
        try {
            const payload = {
                buttons: {
                    left: state.left,
                    right: state.right,
                    middle: state.middle,
                },
                scroll_up: state.scroll_up,
                scroll_down: state.scroll_down,
                double_click_detected: doubleClickDetected,
            };
            const result = await saveTestResult("mouse", window.SESSION_ID, payload);
            window.location.href = result.next_url;
        } catch (err) {
            alert("Could not save mouse test result: " + err.message);
            continueBtn.disabled = false;
            continueBtn.textContent = "Continue to Keyboard Test";
        }
    });
})();
