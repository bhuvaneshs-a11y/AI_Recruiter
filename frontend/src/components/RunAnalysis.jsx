import { useEffect, useRef, useState } from "react";
import { fetchAnalysisJob, fetchJobOpenings, startAnalysis } from "../api";

const POLL_INTERVAL_MS = 2000;

export default function RunAnalysis({ initialJob, onJobConsumed }) {
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [limit, setLimit] = useState(5);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);
  const [total, setTotal] = useState(null);
  const [jobStatus, setJobStatus] = useState("idle"); // idle | running | done | error
  const pollRef = useRef(null);

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

  // Stop polling if the component unmounts mid-run (e.g. switching tabs).
  useEffect(() => () => clearInterval(pollRef.current), []);

  async function handleRun() {
    setRunning(true);
    setJobStatus("running");
    setError(null);
    setResults([]);
    setTotal(null);
    try {
      const { job_id } = await startAnalysis(limit, selectedJobId || null);
      pollRef.current = setInterval(async () => {
        try {
          const job = await fetchAnalysisJob(job_id);
          setResults(job.results);
          setTotal(job.total);
          if (job.status === "done" || job.status === "error") {
            clearInterval(pollRef.current);
            setRunning(false);
            setJobStatus(job.status);
            if (job.status === "error") setError(job.error);
          }
        } catch (e) {
          clearInterval(pollRef.current);
          setRunning(false);
          setJobStatus("error");
          setError(e.message);
        }
      }, POLL_INTERVAL_MS);
    } catch (e) {
      setError(e.message);
      setRunning(false);
      setJobStatus("error");
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
          Processing {total !== null ? `${results.length} of ${total}` : "..."} candidates
          (several run concurrently) - each involves real resume parsing, GitHub/portfolio
          verification, and LLM scoring, so this can still take a while.
        </p>
      )}

      {error && <p className="error">Error: {error}</p>}

      {results && results.length > 0 && (
        <div className="results">
          <h3>
            {jobStatus === "done"
              ? `Processed ${results.length} candidate(s)${selectedJobId ? ", ranked best fit first" : ""}`
              : `${results.length}${total !== null ? ` of ${total}` : ""} candidate(s) done so far...`}
          </h3>
          <div className="results-table-wrap">
            <table className="results-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Candidate</th>
                  <th>Credibility</th>
                  {selectedJobId && <th>Job Fit</th>}
                  {selectedJobId && <th>Confidence</th>}
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => {
                  const isBest = i === 0 && r.report && selectedJobId && jobStatus === "done";
                  return (
                    <tr key={r.zoho_id} className={isBest ? "best-row" : ""}>
                      <td>{i + 1}</td>
                      <td>
                        {r.full_name || r.zoho_id}
                        {isBest && <span className="best-badge">Best Match</span>}
                      </td>
                      {r.report ? (
                        <>
                          <td>{r.report.overall_credibility_score}</td>
                          {selectedJobId && <td>{r.report.overall_fit_score ?? "—"}</td>}
                          {selectedJobId && <td>{r.report.confidence ?? "—"}</td>}
                          <td className="recommendation-cell">{r.report.recommendation}</td>
                        </>
                      ) : (
                        <td className="error" colSpan={selectedJobId ? 4 : 2}>
                          {r.failure_reason === "processing_error"
                            ? "Failed to analyze (resume parsing/verification/LLM error - check server logs)"
                            : "Failed to analyze (no resume attachment found)"}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
