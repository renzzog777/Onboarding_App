(function () {
    // A simplified ANSI keyboard layout using KeyboardEvent.code values.
    const LAYOUT = [
        [["Escape","Esc"]],
        [["Backquote","`"],["Digit1","1"],["Digit2","2"],["Digit3","3"],["Digit4","4"],["Digit5","5"],["Digit6","6"],["Digit7","7"],["Digit8","8"],["Digit9","9"],["Digit0","0"],["Minus","-"],["Equal","="],["Backspace","Bksp","wide-2"]],
        [["Tab","Tab","wide-1"],["KeyQ","Q"],["KeyW","W"],["KeyE","E"],["KeyR","R"],["KeyT","T"],["KeyY","Y"],["KeyU","U"],["KeyI","I"],["KeyO","O"],["KeyP","P"],["BracketLeft","["],["BracketRight","]"],["Backslash","\\"]],
        [["CapsLock","Caps","wide-1"],["KeyA","A"],["KeyS","S"],["KeyD","D"],["KeyF","F"],["KeyG","G"],["KeyH","H"],["KeyJ","J"],["KeyK","K"],["KeyL","L"],["Semicolon",";"],["Quote","'"],["Enter","Enter","wide-2"]],
        [["ShiftLeft","Shift","wide-2"],["KeyZ","Z"],["KeyX","X"],["KeyC","C"],["KeyV","V"],["KeyB","B"],["KeyN","N"],["KeyM","M"],["Comma",","],["Period","."],["Slash","/"],["ShiftRight","Shift","wide-2"]],
        [["ControlLeft","Ctrl"],["AltLeft","Opt"],["MetaLeft","Cmd"],["Space","Space","wide-space"],["MetaRight","Cmd"],["AltRight","Opt"],["ArrowLeft","\u2190"],["ArrowUp","\u2191"],["ArrowDown","\u2193"],["ArrowRight","\u2192"]],
        // Numeric keypad - the Macally keyboards sent to advisors are
        // full-size with a numpad, so it's included in what gets tested.
        [["NumLock","Num"],["NumpadDivide","/"],["NumpadMultiply","*"],["NumpadSubtract","-"]],
        [["Numpad7","7"],["Numpad8","8"],["Numpad9","9"],["NumpadAdd","+"]],
        [["Numpad4","4"],["Numpad5","5"],["Numpad6","6"]],
        [["Numpad1","1"],["Numpad2","2"],["Numpad3","3"],["NumpadEnter","Enter"]],
        [["Numpad0","0","wide-1"],["NumpadDecimal","."]],
    ];

    const layoutEl = document.getElementById("keyboardLayout");
    const allEntries = LAYOUT.flat();
    const totalKeys = allEntries.length;
    const keyElements = {};

    LAYOUT.forEach((row) => {
        const rowEl = document.createElement("div");
        rowEl.className = "kb-row";
        row.forEach(([code, label, extraClass]) => {
            const keyEl = document.createElement("div");
            keyEl.className = "kb-key" + (extraClass ? " " + extraClass : "");
            keyEl.textContent = label;
            keyEl.dataset.code = code;
            rowEl.appendChild(keyEl);
            keyElements[code] = keyEl;
        });
        layoutEl.appendChild(rowEl);
    });

    const pressed = new Set();
    const progressText = document.getElementById("progressText");
    const continueBtn = document.getElementById("continueBtn");

    function updateProgress() {
        const percent = Math.round((pressed.size / totalKeys) * 100);
        progressText.textContent = `${percent}% of layout tested (${pressed.size} keys)`;
    }

    window.addEventListener("keydown", (e) => {
        const el = keyElements[e.code];
        if (el) {
            // Prevent the browser's own default behavior for any key we're
            // tracking - most importantly Enter, which would otherwise
            // "click" the Continue button if it happens to have focus,
            // and Space/Tab, which would scroll the page or shift focus.
            // There's no text input on this page, so this is always safe.
            e.preventDefault();
            el.classList.add("pressed");
            pressed.add(e.code);
            updateProgress();
        }
    });

    continueBtn.addEventListener("click", async () => {
        const percentTested = Math.round((pressed.size / totalKeys) * 100);
        const incompleteReason = document.getElementById("incompleteReasonInput").value.trim();
        const incompleteError = document.getElementById("keyboardIncompleteError");
        if (percentTested < 100 && !incompleteReason) {
            incompleteError.style.display = "block";
            return;
        }
        incompleteError.style.display = "none";

        continueBtn.disabled = true;
        continueBtn.textContent = "Saving...";
        try {
            const missingKeys = allEntries
                .filter(([code]) => !pressed.has(code))
                .map(([, label]) => label);
            const payload = {
                keys_pressed: Array.from(pressed),
                percent_tested: percentTested,
                missing_keys: missingKeys,
                incomplete_reason: percentTested < 100 ? incompleteReason : null,
            };
            const result = await saveTestResult("keyboard", window.SESSION_ID, payload);
            window.location.href = result.next_url;
        } catch (err) {
            alert("Could not save keyboard test result: " + err.message);
            continueBtn.disabled = false;
            continueBtn.textContent = "Continue to Headset Test";
        }
    });
})();
