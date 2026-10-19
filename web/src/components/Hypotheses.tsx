import { pct } from "../format";
import type { Hypothesis } from "../types";

export function Hypotheses({ items, truth }: { items: Hypothesis[]; truth?: string }) {
  return (
    <div className="hyp">
      {items.map((h) => (
        <div key={h.root_cause_code} style={{ display: "contents" }} title={h.rationale}>
          <span className={"code" + (h.root_cause_code === truth ? " truth" : "")}>{h.root_cause_code}</span>
          <div className="track">
            <div className="fill" style={{ width: `${Math.max(0, Math.min(1, h.confidence)) * 100}%` }} />
          </div>
          <span className="val">{pct(h.confidence, 0)}</span>
        </div>
      ))}
    </div>
  );
}
