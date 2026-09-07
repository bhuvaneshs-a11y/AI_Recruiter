import { useEffect, useState } from "react";
import { fetchJobOpenings } from "../api";

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
        <div className="job-card" key={job.id}>
          <div className="job-card-header" onClick={() => setExpandedId(expandedId === job.id ? null : job.id)}>
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
          {expandedId === job.id && job.description && (
            <p className="job-description">{job.description}</p>
          )}
          <div className="job-actions">
            {job.description && (
              <button className="link-button" onClick={() => setExpandedId(expandedId === job.id ? null : job.id)}>
                {expandedId === job.id ? "Hide description" : "Show full description"}
              </button>
            )}
            <button className="analyze-button" onClick={() => onAnalyze(job)}>
              Analyze Applicants
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
