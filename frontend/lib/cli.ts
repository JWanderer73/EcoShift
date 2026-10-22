import { toOffsetIso } from "@/lib/format";

export interface CliCommandOptions {
  region: string;
  durationHours: number;
  /** Null means the end of the forecast, which is the CLI's default, so the flag is left out. */
  deadline: Date | null;
}

/**
 * The `carbon windows` command that asks the CLI the same question as the dashboard's planner.
 * Flags follow the carbon CLI design spec; the deadline carries its UTC offset so the command
 * means the same thing on any machine.
 */
export function buildCliCommand({ region, durationHours, deadline }: CliCommandOptions): string {
  const deadlineFlag = deadline ? ` --deadline ${toOffsetIso(deadline)}` : "";
  return `carbon windows --duration ${durationHours}h${deadlineFlag} --region ${region}`;
}
