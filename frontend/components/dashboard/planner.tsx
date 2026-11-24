"use client";

import { useState } from "react";
import type { PriceWindow } from "@/lib/api/types";
import { JOB_LENGTH_PRESETS, MAX_JOB_HOURS, MAX_KW, MIN_JOB_HOURS } from "@/lib/config";
import { deadlinePresets } from "@/lib/deadline";
import { formatDayTime, formatHours, formatPrice, formatRange, formatUsd, toDateTimeLocal } from "@/lib/format";
import { cn } from "@/lib/utils";

export const fieldLabel = "text-sm font-medium text-ink-2";
const inputClass =
  "h-9 rounded-lg border border-border bg-surface px-3 text-sm text-ink placeholder:text-muted focus-visible:outline-2 focus-visible:outline-forecast";

/** A one-tap option button; the active one is filled. */
function chipClass(active: boolean) {
  return cn(
    "h-9 min-w-12 rounded-lg border px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
    active ? "border-ink bg-ink text-page" : "border-border bg-surface text-ink-2 enabled:hover:bg-surface-2",
  );
}

/** Preset chips plus a custom whole-hour field. */
export function JobLengthPicker({ value, onChange }: { value: number; onChange: (hours: number) => void }) {
  // Kept separately so typing "12" doesn't get interrupted when "1" matches a preset.
  const [draft, setDraft] = useState("");
  const customActive = draft !== "" && Number(draft) === value;

  return (
    <fieldset>
      <legend className={fieldLabel}>Job length</legend>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {JOB_LENGTH_PRESETS.map((hours) => {
          const active = hours === value && !customActive;
          return (
            <button
              key={hours}
              type="button"
              aria-pressed={active}
              onClick={() => {
                setDraft("");
                onChange(hours);
              }}
              className={chipClass(active)}
            >
              {formatHours(hours)}
            </button>
          );
        })}
        <label className="flex items-center gap-1.5 text-sm text-ink-2">
          <span className="sr-only">Custom length in hours</span>
          <input
            type="number"
            inputMode="numeric"
            min={MIN_JOB_HOURS}
            max={MAX_JOB_HOURS}
            step={1}
            placeholder="Other"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              const hours = Number(e.target.value);
              if (Number.isInteger(hours) && hours >= MIN_JOB_HOURS && hours <= MAX_JOB_HOURS) onChange(hours);
            }}
            className={cn(inputClass, "w-20", customActive && "border-ink")}
          />
          h
        </label>
      </div>
    </fieldset>
  );
}

/** Average power draw of the job in kW; it sets the dollar figures (cost = price x kWh / 1000). */
export function PowerField({ value, onChange }: { value: number; onChange: (kw: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  return (
    <label className="flex flex-col gap-2">
      <span className={fieldLabel}>Power draw</span>
      <span className="flex items-center gap-1.5 text-sm text-ink-2">
        <input
          type="number"
          inputMode="decimal"
          min={0.1}
          max={MAX_KW}
          step="any"
          aria-label="Average power draw in kilowatts"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            const kw = Number(e.target.value);
            if (Number.isFinite(kw) && kw > 0 && kw <= MAX_KW) onChange(kw);
          }}
          className={cn(inputClass, "w-24")}
        />
        kW
      </span>
    </label>
  );
}

export interface DeadlineFieldProps {
  value: Date;
  /** Start of the forecast's first hour; the presets are wall-clock times after it. */
  forecastStart: Date;
  /** Earliest deadline that leaves room for the job. */
  min: Date;
  /** End of the forecast. */
  max: Date;
  isCustom: boolean;
  onChange: (localValue: string | null) => void;
}

/** "Must finish by": any time in the forecast, a preset, or a custom date and time. */
export function DeadlineField({ value, forecastStart, min, max, isCustom, onChange }: DeadlineFieldProps) {
  // Stays open while someone types a custom time, even if it passes through a preset's value.
  const [customOpen, setCustomOpen] = useState(false);
  const presets = deadlinePresets(forecastStart);
  const activePreset = isCustom ? presets.find((p) => p.time.getTime() === value.getTime()) : undefined;
  const showCustom = customOpen || (isCustom && !activePreset);

  function pick(localValue: string | null) {
    setCustomOpen(false);
    onChange(localValue);
  }

  return (
    <fieldset>
      <legend className={fieldLabel}>Must finish by</legend>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" aria-pressed={!isCustom && !showCustom} onClick={() => pick(null)} className={chipClass(!isCustom && !showCustom)}>
          Any time
        </button>
        {presets.map(({ label, time }) => {
          const fits = time >= min && time <= max;
          const active = !showCustom && activePreset?.label === label;
          return (
            <button
              key={label}
              type="button"
              aria-pressed={active}
              disabled={!fits}
              title={fits ? formatDayTime(time) : "Too soon for this job"}
              onClick={() => pick(toDateTimeLocal(time))}
              className={chipClass(active)}
            >
              {label}
            </button>
          );
        })}
        <button type="button" aria-pressed={showCustom} onClick={() => setCustomOpen(true)} className={chipClass(showCustom)}>
          Custom
        </button>
        {showCustom && (
          <label>
            <span className="sr-only">Custom deadline</span>
            <input
              type="datetime-local"
              step={3600}
              min={toDateTimeLocal(min)}
              max={toDateTimeLocal(max)}
              value={toDateTimeLocal(value)}
              onChange={(e) => onChange(e.target.value || null)}
              className={inputClass}
            />
          </label>
        )}
      </div>
      <p className="mt-1.5 text-xs text-muted">Forecast runs until {formatDayTime(max)}.</p>
    </fieldset>
  );
}

function savingsLabel(window: PriceWindow, isNow: boolean): string {
  if (isNow) return "Starts now";
  if (window.saved_usd > 0) return `Saves ${formatUsd(window.saved_usd)}`;
  if (window.saved_usd < 0) return `Costs ${formatUsd(-window.saved_usd)} more`;
  return "Same as now";
}

export interface WindowListProps {
  windows: PriceWindow[];
  /** Start of the current hour, to label a window that starts now. */
  firstHour: string;
  /** Start of the job as placed on the chart, to mark the matching window. */
  jobStartTime: string | null;
  highlightedRank: number | null;
  onHighlight: (rank: number | null) => void;
  onSelect: (window: PriceWindow) => void;
}

/** The ranked start times. Hovering one highlights it on the chart; clicking moves the job there. */
export function WindowList({ windows, firstHour, jobStartTime, highlightedRank, onHighlight, onSelect }: WindowListProps) {
  return (
    <ol className="space-y-2" aria-label="Best start times">
      {windows.map((w) => {
        const selected = w.start === jobStartTime;
        return (
          <li key={w.rank}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(w)}
              onMouseEnter={() => onHighlight(w.rank)}
              onMouseLeave={() => onHighlight(null)}
              onFocus={() => onHighlight(w.rank)}
              onBlur={() => onHighlight(null)}
              className={cn(
                "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors",
                selected ? "border-window bg-window/10" : "border-border bg-surface",
                highlightedRank === w.rank && !selected && "bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
                  w.rank === 1 ? "bg-window text-on-window" : "bg-surface-2 text-ink-2",
                )}
              >
                {w.rank}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-ink">{formatRange(new Date(w.start), new Date(w.end))}</span>
                <span className="block text-xs text-muted tabular-nums">{formatUsd(w.cost_usd)} · avg {formatPrice(w.avg_price_usd_per_mwh)}/MWh</span>
              </span>
              <span className="shrink-0 text-right text-sm font-semibold text-ink">{savingsLabel(w, w.start === firstHour)}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
