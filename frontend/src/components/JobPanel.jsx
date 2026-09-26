import React from "react";

export default function JobPanel({
  onSolve,
  job,
  resultField,
  setResultField,
  deformScale,
  setDeformScale,
  solving,
}) {
  return (
    <div className="panel">
      <h3>Solve</h3>
      <button className="primary" onClick={onSolve} disabled={solving}>
        {solving ? "Solving..." : "Run Solver"}
      </button>

      {job && (
        <div className="job-status">
          <p>
            Status: <strong>{job.status}</strong>{" "}
            {job.solver_used && <span className="tag">{job.solver_used}</span>}
          </p>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${(job.progress || 0) * 100}%` }} />
          </div>
          {job.status === "completed" && (
            <>
              <p>Max displacement: {job.results.max_displacement?.toExponential(3)} m</p>
              <p>Max von Mises stress: {(job.results.max_von_mises / 1e6).toFixed(3)} MPa</p>

              <div className="field-row">
                <label>Result field</label>
                <select value={resultField} onChange={(e) => setResultField(e.target.value)}>
                  <option value="von_mises">Von Mises Stress</option>
                  <option value="displacement">Displacement Magnitude</option>
                  <option value="none">None (plain shading)</option>
                </select>
              </div>

              <div className="field-row">
                <label>Deformation scale</label>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={deformScale}
                  onChange={(e) => setDeformScale(parseFloat(e.target.value))}
                />
                <span>{deformScale}x</span>
              </div>
            </>
          )}
          {job.status === "failed" && <pre className="error-log">{job.log}</pre>}
        </div>
      )}
    </div>
  );
}
