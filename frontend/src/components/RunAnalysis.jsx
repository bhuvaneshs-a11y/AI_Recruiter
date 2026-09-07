import { useState } from "react";
import { triggerAnalysis } from "../api";

export default function RunAnalysis() {
  const [limit, setLimit] = useState(1);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);

  async function handleRun() {
    setRunning(true);
    setError(null);
    setResults(null);
    try {
      const data = await triggerAnalysis(limit);
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
        </p>
      )}

      {error && <p className="error">Error: {error}</p>}

      {results && (
        <div className="results">
          <h3>Processed {results.length} candidate(s)</h3>
          {results.map((r) => (
            <div className="result-card" key={r.zoho_id}>
              <h4>{r.full_name || r.zoho_id}</h4>
              {r.report ? (
                <>
                  <p>Credibility: <strong>{r.report.overall_credibility_score}</strong></p>
                  {r.report.overall_fit_score !== undefined && (
                    <p>Job fit: <strong>{r.report.overall_fit_score}</strong> ({r.report.confidence} confidence)</p>
                  )}
                  <p className="recommendation">{r.report.recommendation}</p>
                </>
              ) : (
                <p className="error">Failed to analyze this candidate.</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
