import { useState } from "react";
import "./App.css";
import JobOpenings from "./components/JobOpenings";
import RunAnalysis from "./components/RunAnalysis";

const TABS = [
  { id: "job-openings", label: "Active Job Openings", component: JobOpenings },
  { id: "run-analysis", label: "Run Analysis", component: RunAnalysis },
];

function App() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const ActiveComponent = TABS.find((t) => t.id === activeTab).component;

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
        <ActiveComponent />
      </main>
    </div>
  );
}

export default App;
