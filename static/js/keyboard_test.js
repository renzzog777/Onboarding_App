(function () {
    // A simplified ANSI keyboard layout using KeyboardEvent.code values.
    const LAYOUT = [
        [["Escape","Esc"],["F1","F1"],["F2","F2"],["F3","F3"],["F4","F4"],["F5","F5"],["F6","F6"],["F7","F7"],["F8","F8"],["F9","F9"],["F10","F10"],["F11","F11"],["F12","F12"]],
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
            el.classList.add("pressed");
            pressed.add(e.code);
            updateProgress();
        }
    });

    continueBtn.addEventListener("click", async () => {
        continueBtn.disabled = true;
        continueBtn.textContent = "Saving...";
        try {
            const missingKeys = allEntries
                .filter(([code]) => !pressed.has(code))
                .map(([, label]) => label);
            const payload = {
                keys_pressed: Array.from(pressed),
                percent_tested: Math.round((pressed.size / totalKeys) * 100),
                missing_keys: missingKeys,
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
