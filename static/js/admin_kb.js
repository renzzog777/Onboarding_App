// Manage Tutorials: while any guide is Pending/Processing, poll the
// knowledge base status and update the Assistant pills in place (no page
// reload, so a file already chosen in a form is not lost). Stops polling
// once nothing is busy. Text is always set with textContent.
(function () {
    const endpoint = document.currentScript && document.currentScript.dataset.endpoint;
    if (!endpoint) return;
    const PILLS = {
        indexed: ["PASS", "Indexed"],
        needs_ocr: ["PARTIAL", "Needs OCR"],
        failed: ["FAIL", "Failed"],
        processing: ["in_progress kb-busy", "Processing"],
        pending: ["in_progress kb-busy", "Pending"],
    };
    let finishedSomething = false;

    function busy() {
        return document.querySelector(".kb-cell .kb-busy") !== null;
    }

    function update(cell, doc) {
        const pill = cell.querySelector(".status-pill");
        if (!pill || !doc) return;
        const [cls, label] = PILLS[doc.status] || PILLS.pending;
        const wasBusy = pill.classList.contains("kb-busy");
        pill.className = "status-pill " + cls;
        pill.textContent = label;
        pill.title = doc.status === "indexed" ? doc.chunks + " chunks" : doc.error || "";
        if (wasBusy && !pill.classList.contains("kb-busy")) finishedSomething = true;
    }

    async function poll() {
        try {
            const res = await fetch(endpoint, { headers: { Accept: "application/json" } });
            if (!res.ok) return;
            const docs = await res.json();
            document.querySelectorAll(".kb-cell[data-resource]").forEach((cell) => {
                update(cell, docs[cell.dataset.resource]);
            });
        } catch (e) {
            /* network hiccup: try again next tick */
        }
        if (busy()) {
            setTimeout(poll, 4000);
        } else if (finishedSomething) {
            // Retry buttons depend on the final status; show them.
            const note = document.createElement("p");
            note.className = "muted hint";
            note.textContent = "Indexing finished. Reload the page to refresh the actions.";
            const table = document.querySelector(".table-scroll");
            if (table && !document.getElementById("kbDoneNote")) {
                note.id = "kbDoneNote";
                table.after(note);
            }
        }
    }

    if (busy()) setTimeout(poll, 4000);
})();
