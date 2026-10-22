"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

// Example output in the format the carbon CLI design spec describes. Static illustration, not live data.
const TABLE_OUTPUT = `Region CISO · forecast from Oct 21, 6:00 PM · running now: 312.4 gCO₂/kWh
⚠ Synthetic data: not a real forecast.

Rank  Start          End            Avg gCO₂/kWh  CO₂ saved
1     Thu 11:00 AM   Thu 3:00 PM           131.2      58.0%
2     Fri 11:00 AM   Fri 3:00 PM           149.5      52.1%
3     Thu 7:00 AM    Thu 11:00 AM          201.8      35.4%`;

const JSON_OUTPUT = `{
  "region": "CISO",
  "generated_at": "2026-10-22T01:00:00+00:00",
  "stale": false,
  "data_source": "synthetic",
  "job": { "duration_hours": 4, "deadline": "2026-10-24T01:00:00+00:00", "deadline_clamped": false },
  "baseline": { "start": "2026-10-22T01:00:00+00:00", "end": "2026-10-22T05:00:00+00:00", "avg_intensity_g_per_kwh": 312.4 },
  "windows": [
    { "rank": 1, "start": "2026-10-22T18:00:00+00:00", "end": "2026-10-22T22:00:00+00:00",
      "avg_intensity_g_per_kwh": 131.2, "co2_saved_pct": 58.0 },
    …
  ]
}`;

const TABS = {
  table: { label: "For people", command: "carbon windows --duration 4h --region CISO", output: TABLE_OUTPUT },
  json: { label: "For agents", command: "carbon windows --duration 4h --region CISO --json", output: JSON_OUTPUT },
};

type Tab = keyof typeof TABS;

/** A terminal mockup showing the CLI's table and JSON output. */
export function CliShowcase() {
  const [tab, setTab] = useState<Tab>("table");
  const { command, output } = TABS[tab];

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-terminal text-terminal-ink shadow-sm">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-2">
        <div className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-white/20" />
          <span className="size-2.5 rounded-full bg-white/20" />
          <span className="size-2.5 rounded-full bg-white/20" />
        </div>
        <div className="flex gap-1" role="group" aria-label="Output format">
          {(Object.keys(TABS) as Tab[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium",
                tab === key ? "bg-white/15 text-terminal-ink" : "text-terminal-muted hover:text-terminal-ink",
              )}
            >
              {TABS[key].label}
            </button>
          ))}
        </div>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed">
        <span className="text-terminal-accent">$</span> {command}
        {"\n"}
        {output}
      </pre>
    </div>
  );
}
