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
