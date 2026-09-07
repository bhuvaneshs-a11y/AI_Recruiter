const API_BASE = "http://localhost:8000/api";

export async function fetchJobOpenings() {
  const res = await fetch(`${API_BASE}/job-openings`);
  if (!res.ok) throw new Error(`Failed to load job openings (${res.status})`);
  return res.json();
}

export async function triggerAnalysis(limit) {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit }),
  });
  if (!res.ok) throw new Error(`Analysis request failed (${res.status})`);
  return res.json();
}
