async function saveTestResult(testType, sessionId, payload) {
    const res = await fetch(`/api/save-test/${testType}/${sessionId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error(`Failed to save ${testType} result (HTTP ${res.status})`);
    }
    return res.json();
}

// Admin dropdown: close on outside click or Escape.
document.addEventListener("click", (e) => {
    document.querySelectorAll("details.nav-menu[open]").forEach((menu) => {
        if (!menu.contains(e.target)) menu.removeAttribute("open");
    });
});
document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.nav-menu[open]").forEach((menu) => {
        menu.removeAttribute("open");
        menu.querySelector("summary").focus();
    });
});
