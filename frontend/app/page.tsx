import { ArrowRight, Bot, BrainCircuit, Database, Server, Terminal, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { CliShowcase } from "@/components/landing/cli-showcase";
import { HeroLeaves } from "@/components/landing/hero-leaves";
import { LiveForecastCard } from "@/components/landing/live-forecast-card";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { FORECAST_HORIZON_HOURS } from "@/lib/config";

const STEPS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Database,
    title: "Ingest",
    body: "Hourly grid data from EIA-930 and weather from Open-Meteo, checked for gaps, duplicates, and impossible values before they're joined.",
  },
  {
    icon: BrainCircuit,
    title: "Forecast",
    body: `A model predicts carbon intensity ${FORECAST_HORIZON_HOURS} hours ahead. A new model only ships if its backtest error holds up against the current one.`,
  },
  {
    icon: Server,
    title: "Serve",
    body: "A serverless API returns the lowest-emission windows. If the pipeline breaks, it keeps serving the last good forecast and says so.",
  },
  {
    icon: Bot,
    title: "Use",
    body: "This dashboard for people, the carbon CLI for terminals, and an agent skill that has coding agents check before long jobs.",
  },
];

const CLI_POINTS = [
  "A table for people, JSON for coding agents.",
  "The same forecast and ranking as the dashboard.",
  "An agent skill that says when to run it (before long training runs, batch jobs, big builds) and how to read the result.",
];

export default function Home() {
  return (
    <>
      <SiteHeader current="home" />
      <main className="flex-1">
        <div className="relative overflow-hidden">
          <HeroLeaves />
          <section className="relative mx-auto grid max-w-6xl gap-10 px-4 pt-12 pb-16 sm:pt-20 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:pb-24">
            <div>
              <p className="text-sm font-medium text-primary">Carbon-aware scheduling for heavy compute</p>
              <h1 className="mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
                Run heavy jobs when the grid is cleanest.
              </h1>
              <p className="mt-4 max-w-xl text-lg text-pretty text-ink-2">
                The same job emits more or less CO₂ depending on when it runs. EcoShift forecasts grid carbon intensity{" "}
                {FORECAST_HORIZON_HOURS} hours ahead and finds the lowest-emission window for training runs, batch jobs, and builds.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="/dashboard" className={buttonVariants({ variant: "primary", size: "lg" })}>
                  Open the dashboard
                  <ArrowRight aria-hidden />
                </Link>
                <Link href="#cli" className={buttonVariants({ variant: "secondary", size: "lg" })}>
                  <Terminal aria-hidden />
                  Use the CLI
                </Link>
              </div>
            </div>
            <LiveForecastCard />
          </section>
        </div>

        <section id="how-it-works" className="scroll-mt-20 border-t border-border bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:py-20">
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">How it works</h2>
            <p className="mt-2 max-w-2xl text-ink-2">
              A scheduled pipeline does the heavy lifting. Requests only read saved forecasts, so answers are fast and keep
              working when the model doesn&apos;t.
            </p>
            <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map(({ icon: Icon, title, body }, i) => (
                <li key={title} className="rounded-2xl border border-border bg-page p-5">
                  <div className="flex items-center justify-between">
                    <span className="flex size-10 items-center justify-center rounded-xl bg-surface-2">
                      <Icon className="size-5 text-ink" aria-hidden />
                    </span>
                    <span className="text-sm font-medium text-muted tabular-nums">0{i + 1}</span>
                  </div>
                  <h3 className="mt-4 font-semibold">{title}</h3>
                  <p className="mt-1.5 text-sm text-ink-2">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="cli" className="scroll-mt-20 border-t border-border">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:py-20 lg:grid-cols-[1fr_1.2fr] lg:items-center">
            <div>
              <Badge>In development</Badge>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">Built for terminals and coding agents</h2>
              <p className="mt-3 text-ink-2">
                <code className="font-mono text-ink">carbon windows</code> answers the same question as the dashboard. Agents run
                it with <code className="font-mono text-ink">--json</code> before starting a long job and report how much CO₂ waiting
                saves.
              </p>
              <ul className="mt-6 space-y-3 text-sm text-ink-2">
                {CLI_POINTS.map((point) => (
                  <li key={point} className="flex gap-3">
                    <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                    {point}
                  </li>
                ))}
              </ul>
            </div>
            <div className="min-w-0">
              <CliShowcase />
              <p className="mt-2 text-xs text-muted">Example output.</p>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
