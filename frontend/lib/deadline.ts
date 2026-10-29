/** A one-tap "must finish by" option in the planner. */
export interface DeadlinePreset {
  label: string;
  time: Date;
}

/**
 * Wall-clock deadlines people plan around, in the viewer's time zone: midnight at the end of the
 * forecast's first day, and 9 AM the morning after.
 *
 * @param forecastStart Start of the forecast's first hour.
 */
export function deadlinePresets(forecastStart: Date): DeadlinePreset[] {
  const midnight = new Date(forecastStart);
  midnight.setHours(24, 0, 0, 0);
  const tomorrowMorning = new Date(midnight);
  tomorrowMorning.setHours(9);
  return [
    { label: "Midnight", time: midnight },
    { label: "Tomorrow 9 AM", time: tomorrowMorning },
  ];
}
