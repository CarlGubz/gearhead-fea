import React from "react";

export default function JobPanel({
  onSolve,
  job,
  resultField,
  setResultField,
  deformScale,
  setDeformScale,
  solving,
  selectedMode,
  setSelectedMode,
}) {
  const analysisType = job?.results?.analysis_type;

  return (
    <>
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

          {job.status === "completed" && analysisType === "static" && (
            <>
              <p>Max displacement: {job.results.max_displacement?.toExponential(3)} m</p>
              <p>Max von Mises stress: {(job.results.max_von_mises / 1e6).toFixed(3)} MPa</p>

              <div className="field-row">
                <label>Result field</label>
                <select value={resultField} onChange={(e) => setResultField(e.target.value)}>
                  <option value="von_mises">Von Mises Stress</option>
                  <option value="displacement">Displacement Magnitude</option>
                  <option value="principal_max">Max Principal Stress (S1)</option>
                  <option value="principal_min">Min Principal Stress (S3)</option>
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

          {job.status === "completed" && analysisType === "modal" && (
            <>
              <p className="hint">{job.results.frequencies_hz.length} mode(s) computed.</p>
              <div className="list-block">
                <ul>
                  {job.results.frequencies_hz.map((f, i) => (
                    <li
                      key={i}
                      className={selectedMode === i ? "active" : ""}
                      onClick={() => setSelectedMode(i)}
                      style={{ cursor: "pointer" }}
                    >
                      Mode {i + 1}: {f.toFixed(2)} Hz
                    </li>
                  ))}
                </ul>
              </div>
              <div className="field-row">
                <label>Mode shape scale</label>
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

          {job.status === "completed" && analysisType === "thermal" && (
            <>
              <p>Max temperature: {job.results.max_temperature?.toFixed(2)}</p>
              <p>Min temperature: {job.results.min_temperature?.toFixed(2)}</p>
              <p className="hint">Temperature contour shown in model units (matches your BC/material input units).</p>
            </>
          )}

          {job.status === "failed" && <pre className="error-log">{job.log}</pre>}
        </div>
      )}
    </>
  );
}
