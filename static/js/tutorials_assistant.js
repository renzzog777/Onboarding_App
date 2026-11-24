// Tutorials assistant chat panel (see chatbot.py).
// The answer is streamed from the server as NDJSON events:
//   {"type":"sources","sources":[{title, section, url}]}
//   {"type":"delta","text":"..."}      (many)
//   {"type":"done"} | {"type":"error","error":"..."}
// Answers are never inserted as HTML (OWASP LLM05): the small Markdown
// subset the model uses (**bold**, `code`, bullets) is turned into DOM
// nodes whose text is always set as plain text.
(function () {
    const form = document.getElementById("assistantForm");
    if (!form) return;
    const log = document.getElementById("assistantLog");
    const input = document.getElementById("assistantQuestion");
    const send = document.getElementById("assistantSend");
    const clear = document.getElementById("assistantClear");
    const HISTORY_MESSAGES = 4; // last 2 turns, matches chatbot.py
    let history = [];

    function bubble(who) {
        const el = document.createElement("div");
        el.className = "assistant-msg " + who;
        log.appendChild(el);
        log.hidden = false;
        if (clear) clear.hidden = false;
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
            const line = rawLine.replace(/^(\s*)[*-]\s+/, "$1• ");
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
            chip.textContent = s.section ? s.title + " → " + s.section : s.title;
            if (s.url) {
                chip.href = s.url;
                chip.title = "Download the PDF";
            }
            wrap.appendChild(chip);
        });
        el.appendChild(wrap);
    }

    function waiting(el, text) {
        const status = document.createElement("span");
        status.className = "waiting-indicator";
        const spinner = document.createElement("span");
        spinner.className = "spinner";
        const statusText = document.createElement("span");
        statusText.textContent = text;
        status.append(spinner, statusText);
        el.replaceChildren(status);
        return statusText;
    }

    // Yields parsed NDJSON events from a fetch Response as they arrive.
    async function* events(res) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buffer.indexOf("\n")) >= 0) {
                const line = buffer.slice(0, nl).trim();
                buffer = buffer.slice(nl + 1);
                if (line) yield JSON.parse(line);
            }
        }
        if (buffer.trim()) yield JSON.parse(buffer);
    }

    async function ask(question) {
        bubble("user").textContent = question;
        const answer = bubble("bot");
        const statusText = waiting(answer, "Searching the guides...");
        scrollToEnd();
        let text = "";
        let sources = [];
        let failed = null;
        const slow = setTimeout(() => {
            statusText.textContent = "Writing the answer (the local model can take up to half a minute)...";
        }, 6000);
        try {
            const res = await fetch(form.dataset.endpoint || "/tutorials/assistant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question, history: history.slice(-HISTORY_MESSAGES) }),
            });
            const type = res.headers.get("Content-Type") || "";
            if (!res.ok || !type.includes("ndjson")) {
                const data = await res.json().catch(() => ({}));
                failed = data.error || "The assistant is not available right now.";
            } else {
                const body = document.createElement("div");
                for await (const ev of events(res)) {
                    if (ev.type === "sources") {
                        sources = ev.sources || [];
                        statusText.textContent = "Writing the answer...";
                    } else if (ev.type === "delta") {
                        if (!text) answer.replaceChildren(body);
                        text += ev.text;
                        render(body, text);
                        scrollToEnd();
                    } else if (ev.type === "error") {
                        failed = ev.error;
                    }
                }
            }
        } catch (err) {
            failed = "Connection error. Please try again.";
        }
        clearTimeout(slow);
        if (failed && !text) {
            answer.classList.add("error-msg");
            answer.textContent = failed;
        } else {
            if (failed) {
                const note = document.createElement("div");
                note.className = "error-msg";
                note.textContent = failed;
                answer.appendChild(note);
            }
            addSources(answer, sources);
            history.push({ role: "user", content: question }, { role: "assistant", content: text });
            history = history.slice(-HISTORY_MESSAGES);
        }
        scrollToEnd();
    }

    log.hidden = true;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        input.value = "";
        input.disabled = send.disabled = true;
        try {
            await ask(question);
        } finally {
            input.disabled = send.disabled = false;
            input.focus();
        }
    });

    if (clear) {
        clear.addEventListener("click", () => {
            history = [];
            log.replaceChildren();
            log.hidden = true;
            clear.hidden = true;
            input.focus();
        });
    }
})();
