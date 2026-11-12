// Tutorials assistant chat panel (see chatbot.py).
// Answers are never inserted as HTML (OWASP LLM05): the small Markdown
// subset the model uses (**bold**, `code`, bullets) is turned into DOM
// nodes whose text is always set as plain text.
(function () {
    const form = document.getElementById("assistantForm");
    if (!form) return;
    const log = document.getElementById("assistantLog");
    const input = document.getElementById("assistantQuestion");
    const send = document.getElementById("assistantSend");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const phases = ["Searching the guides", "Reading the relevant pages", "Writing the answer"];

    function bubble(who) {
        const el = document.createElement("div");
        el.className = "assistant-msg " + who;
        log.appendChild(el);
        log.hidden = false;
        return el;
    }

    function scrollToEnd() {
        log.scrollTop = log.scrollHeight;
    }

    // Render **bold**, `code` and "* " / "- " bullets safely.
    function render(el, text) {
        el.replaceChildren();
        text.split("\n").forEach((rawLine, i) => {
            if (i) el.append("\n");
            const line = rawLine.replace(/^(\s*)[*-]\s+/, "$1\u2022 ");
            const pattern = /\*\*(.+?)\*\*|`([^`]+)`/g;
            let last = 0;
            let m;
            while ((m = pattern.exec(line))) {
                if (m.index > last) el.append(line.slice(last, m.index));
                const node = document.createElement(m[1] !== undefined ? "strong" : "code");
                node.textContent = m[1] !== undefined ? m[1] : m[2];
                el.append(node);
                last = pattern.lastIndex;
            }
            if (last < line.length) el.append(line.slice(last));
        });
    }

    async function typeOut(el, text) {
        if (reduceMotion) {
            render(el, text);
            return;
        }
        const step = Math.max(1, Math.ceil(text.length / 300));
        for (let i = 0; i < text.length; i += step) {
            render(el, text.slice(0, i + step));
            scrollToEnd();
            await new Promise((r) => setTimeout(r, 12));
        }
    }

    function addSources(el, sources) {
        if (!sources || !sources.length) return;
        const wrap = document.createElement("div");
        wrap.className = "assistant-sources";
        const label = document.createElement("span");
        label.className = "muted";
        label.textContent = "Sources:";
        wrap.appendChild(label);
        sources.forEach((s) => {
            const chip = document.createElement(s.url ? "a" : "span");
            chip.className = "assistant-chip";
            chip.textContent = s.title;
            if (s.url) chip.href = s.url;
            wrap.appendChild(chip);
        });
        el.appendChild(wrap);
    }

    log.hidden = true;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        bubble("user").textContent = question;
        input.value = "";
        input.disabled = send.disabled = true;

        const answer = bubble("bot");
        const status = document.createElement("span");
        status.className = "waiting-indicator";
        const spinner = document.createElement("span");
        spinner.className = "spinner";
        const statusText = document.createElement("span");
        statusText.textContent = phases[0] + "...";
        status.append(spinner, statusText);
        answer.appendChild(status);
        scrollToEnd();
        let phase = 0;
        const timer = setInterval(() => {
            phase = Math.min(phase + 1, phases.length - 1);
            statusText.textContent = phases[phase] + "...";
        }, 3500);

        let data;
        try {
            const res = await fetch(form.dataset.endpoint || "/tutorials/assistant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question }),
            });
            data = await res.json();
        } catch (err) {
            data = { error: "Connection error. Please try again." };
        }
        clearInterval(timer);
        answer.textContent = "";
        if (data.error) answer.classList.add("error-msg");
        const text = document.createElement("div");
        answer.appendChild(text);
        await typeOut(text, data.answer || data.error || "No response.");
        addSources(answer, data.sources);
        scrollToEnd();
        input.disabled = send.disabled = false;
        input.focus();
    });
})();
