"use client";

import { useState } from "react";
import {
  CARBON_PRICE_PRESETS,
  CARBON_PRICE_STEP,
  JOB_LENGTH_PRESETS,
  MAX_CARBON_PRICE,
  MAX_JOB_HOURS,
  MAX_POWER_MW,
  MIN_JOB_HOURS,
  MIN_POWER_MW,
} from "@/lib/config";
import { dollarsSaved, type JobStats, type JobWindow } from "@/lib/cost";
import { deadlinePresets } from "@/lib/deadline";
import { formatDayTime, formatHours, formatIntensity, formatPct, formatRange, formatUsd, toDateTimeLocal } from "@/lib/format";
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

/** Average power draw in MW. Scales the dollar figures only. */
export function PowerField({ value, onChange }: { value: number; onChange: (mw: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  return (
    <label className="flex flex-col gap-2">
      <span className={fieldLabel}>Power draw</span>
      <span className="flex items-center gap-1.5 text-sm text-ink-2">
        <input
          type="number"
          inputMode="decimal"
          min={MIN_POWER_MW}
          max={MAX_POWER_MW}
          step="any"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            const mw = Number(e.target.value);
            if (e.target.value !== "" && mw >= MIN_POWER_MW && mw <= MAX_POWER_MW) onChange(mw);
          }}
          className={cn(inputClass, "w-24")}
        />
        MW
      </span>
    </label>
  );
}

/** The blend: a carbon price in $/tCO₂ added to the power price. 0 ranks by price alone. */
export function CarbonPriceField({ value, onChange, disabled }: { value: number; onChange: (price: number) => void; disabled: boolean }) {
  return (
    <fieldset disabled={disabled} className="disabled:opacity-50">
      <legend className={fieldLabel}>
        Carbon price <span className="font-semibold text-ink tabular-nums">{formatUsd(value)}/t</span>
      </legend>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          type="range"
          min={0}
          max={MAX_CARBON_PRICE}
          step={CARBON_PRICE_STEP}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          aria-label="Carbon price in dollars per tonne"
          aria-valuetext={`${formatUsd(value)} per tonne of CO₂`}
          className="h-9 w-36 accent-[var(--window)]"
        />
        {CARBON_PRICE_PRESETS.map((preset) => (
          <button
            key={preset.value}
            type="button"
            aria-pressed={value === preset.value}
            title={`${formatUsd(preset.value)} per tonne`}
            onClick={() => onChange(preset.value)}
            className={chipClass(value === preset.value)}
          >
            {preset.label}
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted">
        {disabled ? "This API doesn't serve prices yet, so start times are ranked by carbon only." : "Higher favors cleaner hours over cheaper ones."}
      </p>
    </fieldset>
  );
}

/** The window's headline compared with starting now: dollars when priced, CO₂ otherwise. */
function savingsLabel(saved: number | null, co2SavedPct: number, isNow: boolean): string {
  if (isNow) return "Starts now";
  if (saved !== null) {
    if (Math.round(saved) > 0) return `Save ${formatUsd(saved)}`;
    if (Math.round(saved) < 0) return `${formatUsd(-saved)} more`;
    return "Same cost as now";
  }
  if (co2SavedPct > 0) return `${formatPct(co2SavedPct)} less CO₂`;
  if (co2SavedPct < 0) return `${formatPct(co2SavedPct)} more CO₂`;
  return "Same as now";
}

function co2Label(co2SavedPct: number): string {
  if (Math.round(co2SavedPct) === 0) return "same CO₂";
  return `${formatPct(co2SavedPct)} ${co2SavedPct > 0 ? "less" : "more"} CO₂`;
}

export interface WindowListProps {
  windows: JobWindow[];
  /** The same job started now; savings are measured against it. */
  baseline: JobStats;
  powerMw: number;
  durationHours: number;
  /** Start index of the job as placed on the chart, to mark the matching window. */
  jobStart: number | null;
  highlightedRank: number | null;
  onHighlight: (rank: number | null) => void;
  onSelect: (window: JobWindow) => void;
}

/** The ranked start times. Hovering one highlights it on the chart; clicking moves the job there. */
export function WindowList({ windows, baseline, powerMw, durationHours, jobStart, highlightedRank, onHighlight, onSelect }: WindowListProps) {
  return (
    <ol className="space-y-2" aria-label="Best start times">
      {windows.map((w) => {
        const selected = w.startIndex === jobStart;
        const isNow = w.startIndex === 0;
        const saved = dollarsSaved(baseline, w, powerMw, durationHours);
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
                <span className="block text-xs text-muted tabular-nums">
                  {w.avgPrice !== null && <>{formatUsd(w.avgPrice)}/MWh · </>}
                  {formatIntensity(w.avgIntensity)} gCO₂/kWh
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block text-sm font-semibold text-ink">{savingsLabel(saved, w.co2SavedPct, isNow)}</span>
                {saved !== null && !isNow && <span className="block text-xs text-muted">{co2Label(w.co2SavedPct)}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
