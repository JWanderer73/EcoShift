"use client";

import { useState } from "react";
import { buildCliCommand, formatCliJson, formatCliTable } from "@/lib/cli";
import { DEFAULT_JOB_HOURS, DEFAULT_REGION } from "@/lib/config";
import { useMinuteClock } from "@/lib/hooks/use-clock";
import { useDefaultForecast } from "@/lib/hooks/use-default-forecast";
import { cn } from "@/lib/utils";

const COMMAND = buildCliCommand({ region: DEFAULT_REGION, durationHours: DEFAULT_JOB_HOURS, deadline: null });

const TABS = {
  table: { label: "For people", command: COMMAND },
  json: { label: "For agents", command: `${COMMAND} --json` },
};

type Tab = keyof typeof TABS;

/** A terminal showing what the carbon CLI prints for the same forecast as the hero card, as a table or JSON. */
export function CliShowcase() {
  const [tab, setTab] = useState<Tab>("table");
  const { forecast, windows } = useDefaultForecast();
  const now = useMinuteClock();
  const error = forecast.error ?? windows.error;

  let output;
  if (error) {
    output = `Error: ${error.message}`;
  } else if (!forecast.data || !windows.data || now === null) {
    output = <span className="animate-pulse text-terminal-muted">▍</span>;
  } else {
    output = tab === "table" ? formatCliTable(windows.data, forecast.data, now) : formatCliJson(windows.data);
  }

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
      {/* Terminal line height so box-drawing lines join. Tall enough for the table output (16 lines) so
          switching tabs doesn't jump; the JSON scrolls. */}
      <pre className="h-[16.5rem] overflow-auto p-4 font-terminal text-xs leading-[1.2]" data-testid="cli-output">
        <span className="text-terminal-accent">$</span> {TABS[tab].command}
        {"\n"}
        {output}
      </pre>
    </div>
  );
}
