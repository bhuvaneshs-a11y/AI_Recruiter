// VITE_API_BASE lets a deployed build point at its real backend URL instead
// of localhost - set it as a build-time env var on whatever host serves this
// frontend (Vite only exposes env vars prefixed with VITE_ to client code).
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export async function fetchJobOpenings() {
  const res = await fetch(`${API_BASE}/job-openings`);
  if (!res.ok) throw new Error(`Failed to load job openings (${res.status})`);
  return res.json();
}

export async function saveJobOpeningOverride(zohoId, title, customDescription, customPrompt) {
  const res = await fetch(`${API_BASE}/job-openings/${zohoId}/override`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title,
      custom_description: customDescription,
      custom_prompt: customPrompt,
    }),
  });
  if (!res.ok) throw new Error(`Failed to save job opening changes (${res.status})`);
  return res.json();
}

export async function startAnalysis(limit, jobOpeningId) {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit, job_opening_id: jobOpeningId || null }),
  });
  if (!res.ok) throw new Error(`Analysis request failed (${res.status})`);
  return res.json(); // {job_id}
}

export async function fetchAnalysisJob(jobId) {
  const res = await fetch(`${API_BASE}/analyze/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch analysis status (${res.status})`);
  return res.json(); // {status, total, results, error}
}
