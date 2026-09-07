import { useState } from "react";
import "./App.css";
import JobOpenings from "./components/JobOpenings";
import RunAnalysis from "./components/RunAnalysis";

const TABS = [
  { id: "job-openings", label: "Active Job Openings" },
  { id: "run-analysis", label: "Run Analysis" },
];

function App() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [selectedJob, setSelectedJob] = useState(null);

  function analyzeJob(job) {
    setSelectedJob(job);
    setActiveTab("run-analysis");
  }

  return (
    <div className="app">
      <header>
        <h1>AI Recruiter</h1>
      </header>
      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <main>
        {activeTab === "job-openings" && <JobOpenings onAnalyze={analyzeJob} />}
        {activeTab === "run-analysis" && (
          <RunAnalysis initialJob={selectedJob} onJobConsumed={() => setSelectedJob(null)} />
        )}
      </main>
    </div>
  );
}

export default App;
