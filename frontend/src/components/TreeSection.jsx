import React, { useState } from "react";

export default function TreeSection({ icon, title, badge, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="tree-section">
      <div className="tree-section-header" onClick={() => setOpen((o) => !o)}>
        <span className={`tree-chevron ${open ? "open" : ""}`}>❯</span>
        <span className="tree-icon">{icon}</span>
        <span className="tree-section-title">{title}</span>
        {badge !== undefined && badge !== null && <span className="tree-section-badge">{badge}</span>}
      </div>
      {open && <div className="tree-section-body">{children}</div>}
    </div>
  );
}
