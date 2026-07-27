import type { AnalyticalTimeSettings } from "./api";

export type AnalyticalTimeBasis = Pick<AnalyticalTimeSettings, "time_zone" | "day_boundary_minutes">;

export const UTC_TIME_BASIS: AnalyticalTimeBasis = {
  time_zone: "UTC",
  day_boundary_minutes: 0,
};

type LocalParts = { year: number; month: number; day: number; hour: number; minute: number };

function partsAt(iso: string, timeZone: string): LocalParts | null {
  const instant = new Date(iso);
  if (!Number.isFinite(instant.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant);
  const number = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value);
  return { year: number("year"), month: number("month"), day: number("day"), hour: number("hour"), minute: number("minute") };
}

export function analyticalDayKey(iso: string, basis: AnalyticalTimeBasis): string | null {
  const local = partsAt(iso, basis.time_zone);
  if (!local) return null;
  const civil = new Date(Date.UTC(local.year, local.month - 1, local.day));
  if (local.hour * 60 + local.minute < basis.day_boundary_minutes) civil.setUTCDate(civil.getUTCDate() - 1);
  return civil.toISOString().slice(0, 10);
}

export function localHour(iso: string, basis: AnalyticalTimeBasis): number | null {
  return partsAt(iso, basis.time_zone)?.hour ?? null;
}

export function analyticalWeekKey(dayKey: string): string {
  const day = new Date(`${dayKey}T00:00:00Z`);
  const mondayOffset = (day.getUTCDay() + 6) % 7;
  day.setUTCDate(day.getUTCDate() - mondayOffset);
  return day.toISOString().slice(0, 10);
}

export function analyticalDayOfWeek(dayKey: string): number {
  return (new Date(`${dayKey}T00:00:00Z`).getUTCDay() + 6) % 7;
}

export function currentAnalyticalDayOfWeek(
  basis: AnalyticalTimeBasis,
  now: Date = new Date(),
): number | null {
  const day = analyticalDayKey(now.toISOString(), basis);
  return day ? analyticalDayOfWeek(day) : null;
}

export function timeBasisLabel(basis: AnalyticalTimeBasis): string {
  const hours = Math.floor(basis.day_boundary_minutes / 60);
  const minutes = basis.day_boundary_minutes % 60;
  return `${basis.time_zone} · day starts ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}
