import { useEffect, useState } from "react";
import { fetchJobOpenings, triggerAnalysis } from "../api";

export default function RunAnalysis({ initialJob, onJobConsumed }) {
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [limit, setLimit] = useState(5);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);

  useEffect(() => {
    fetchJobOpenings()
      .then(setJobs)
      .catch((e) => setError(e.message))
      .finally(() => setJobsLoading(false));
  }, []);

  useEffect(() => {
    if (initialJob) {
      setSelectedJobId(initialJob.id);
      onJobConsumed?.();
    }
  }, [initialJob]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    setResults(null);
    try {
      const data = await triggerAnalysis(limit, selectedJobId || null);
      setResults(data.results);
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="run-analysis">
      <div className="run-controls">
        <label>
          Job opening:
          <select
            value={selectedJobId}
            onChange={(e) => setSelectedJobId(e.target.value)}
            disabled={running || jobsLoading}
          >
            <option value="">— Any candidate (no job context) —</option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>{job.title}</option>
            ))}
          </select>
        </label>
        <label>
          Candidates to process:
          <input
            type="number"
            min="1"
            max="20"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            disabled={running}
          />
        </label>
        <button onClick={handleRun} disabled={running}>
          {running ? "Running..." : "Run Analysis"}
        </button>
      </div>

      {running && (
        <p className="hint">
          This calls the real pipeline (resume parsing, GitHub/portfolio verification, LLM scoring) for
          each candidate - it can take anywhere from several seconds to a minute or more per candidate.
          {selectedJobId && " A job opening can have thousands of applicants, so only the number above is processed."}
        </p>
      )}

      {error && <p className="error">Error: {error}</p>}

      {results && (
        <div className="results">
          <h3>Processed {results.length} candidate(s){selectedJobId && ", ranked best fit first"}</h3>
          {results.map((r, i) => (
            <div className="result-card" key={r.zoho_id}>
              <h4>
                {r.full_name || r.zoho_id}
                {i === 0 && r.report && selectedJobId && <span className="best-badge">Best Match</span>}
              </h4>
              {r.report ? (
                <>
                  <p>Credibility: <strong>{r.report.overall_credibility_score}</strong></p>
                  {r.report.overall_fit_score !== undefined && (
                    <p>Job fit: <strong>{r.report.overall_fit_score}</strong> ({r.report.confidence} confidence)</p>
                  )}
                  <p className="recommendation">{r.report.recommendation}</p>
                </>
              ) : (
                <p className="error">Failed to analyze this candidate (no resume attachment found).</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
