import { useEffect, useState } from "react";
import { fetchJobOpenings, saveJobOpeningOverride } from "../api";

function JobCard({ job, expanded, onToggleExpand, onAnalyze }) {
  const [description, setDescription] = useState(job.custom_description || job.description || "");
  const [prompt, setPrompt] = useState(job.custom_prompt || "");
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved | error

  const isOverridden = Boolean(job.custom_description);

  async function handleSave() {
    setSaveState("saving");
    try {
      await saveJobOpeningOverride(job.id, job.title, description, prompt);
      setSaveState("saved");
    } catch (e) {
      setSaveState("error");
    }
  }

  return (
    <div className="job-card">
      <div className="job-card-header" onClick={onToggleExpand}>
        <h3>{job.title}</h3>
        <span className="badge">{job.status}</span>
      </div>
      <div className="job-meta">
        <span>{job.job_type || "—"}</span>
        <span>{job.remote ? "Remote" : "On-site"}</span>
        <span>{job.number_of_positions} position(s)</span>
        <span>{job.industry || "—"}</span>
      </div>
      {job.required_skills && (
        <p className="job-skills"><strong>Required skills:</strong> {job.required_skills}</p>
      )}

      {expanded && (
        <div className="job-edit">
          <label>
            Job description {isOverridden && <span className="hint">(edited locally, not synced to Zoho)</span>}
            <textarea
              rows={8}
              value={description}
              onChange={(e) => { setDescription(e.target.value); setSaveState("idle"); }}
            />
          </label>
          <label>
            Search prompt <span className="hint">(optional - extra criteria for this job's applicant analysis, e.g. "must know Kubernetes, prioritize RAG experience")</span>
            <textarea
              rows={3}
              value={prompt}
              onChange={(e) => { setPrompt(e.target.value); setSaveState("idle"); }}
            />
          </label>
          <div className="job-edit-actions">
            <button onClick={handleSave} disabled={saveState === "saving"}>
              {saveState === "saving" ? "Saving..." : "Save"}
            </button>
            {saveState === "saved" && <span className="save-status saved">Saved</span>}
            {saveState === "error" && <span className="save-status error">Failed to save</span>}
          </div>
        </div>
      )}

      <div className="job-actions">
        <button className="link-button" onClick={onToggleExpand}>
          {expanded ? "Hide description & prompt" : "Edit description & prompt"}
        </button>
        <button className="analyze-button" onClick={() => onAnalyze(job)}>
          Analyze Applicants
        </button>
      </div>
    </div>
  );
}

export default function JobOpenings({ onAnalyze }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    fetchJobOpenings()
      .then(setJobs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading active job openings from Zoho Recruit...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (jobs.length === 0) return <p>No active job openings found.</p>;

  return (
    <div className="job-openings">
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          expanded={expandedId === job.id}
          onToggleExpand={() => setExpandedId(expandedId === job.id ? null : job.id)}
          onAnalyze={onAnalyze}
        />
      ))}
    </div>
  );
}
