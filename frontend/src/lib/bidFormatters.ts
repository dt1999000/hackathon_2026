// Formatting helpers for the bids Dashboard. Kept separate from the API
// client so they're easy to reuse in the header, the table and toasts.

function stripTimezoneSuffix(value: string): string {
  return value.replace(/(Z|[+-]\d{2}:\d{2})$/, "")
}

function toDate(value: string): Date | null {
  const parsed = new Date(stripTimezoneSuffix(value))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/** Like toDate, but keeps the timestamp's own timezone (or assumes UTC when
 * none is given) instead of stripping it -- for a real instant in time
 * (last_refreshed_at, a UTC timestamp from the backend) that should convert
 * to the viewer's local clock, not be read as if its UTC digits were
 * already local. toDate/stripTimezoneSuffix stay as they are for
 * formatDeadline below, which deliberately shows a submission deadline
 * exactly as the source stated it (a German-local wall time) rather than
 * converting it to whichever timezone the viewer happens to be in. */
function toDateWithTimezone(value: string): Date | null {
  const hasTimezone = /(Z|[+-]\d{2}:\d{2})$/.test(value)
  const parsed = new Date(hasTimezone ? value : `${value}Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function pad2(n: number): string {
  return String(n).padStart(2, "0")
}

/** "DD/MM/YY" */
export function formatDateDDMMYY(date: Date): string {
  return `${pad2(date.getDate())}/${pad2(date.getMonth() + 1)}/${pad2(date.getFullYear() % 100)}`
}

/** "HH:MM" */
export function formatTimeHHMM(date: Date): string {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

/** "Last updated: 14:32, 18/09/26" (or "Last updated: never" before the
 * first successful refresh). */
export function formatLastUpdated(isoTimestamp: string | null): string {
  if (!isoTimestamp) return "Last updated: never"
  const date = toDateWithTimezone(isoTimestamp)
  if (!date) return "Last updated: never"
  return `Last updated: ${formatTimeHHMM(date)}, ${formatDateDDMMYY(date)}`
}

/** Submission deadline as "DD/MM/YY, HH:MM", date-only, or a fallback when
 * the source never gave a deadline. */
export function formatDeadline(
  deadlineDate: string | null,
  deadlineTime: string | null,
): string {
  if (!deadlineDate) return "No deadline listed"

  const datePart = stripTimezoneSuffix(deadlineDate)
  const timePart = deadlineTime ? stripTimezoneSuffix(deadlineTime) : null
  const combined = timePart ? `${datePart}T${timePart}` : datePart
  const date = toDate(combined)

  if (!date) return deadlineDate
  return timePart
    ? `${formatDateDDMMYY(date)}, ${formatTimeHHMM(date)}`
    : formatDateDDMMYY(date)
}

/** "€ 1,250,000" / "USD 500" / "Not specified" when no value is on file. */
export function formatPrice(
  value: number | null,
  currency: string | null,
): string {
  if (value === null || value === undefined) return "Not specified"

  const formattedNumber = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(value)

  if (!currency) return formattedNumber
  if (currency === "EUR") return `€ ${formattedNumber}`
  return `${currency} ${formattedNumber}`
}

export function sourceLabel(sourceSystem: string): string {
  return sourceSystem === "TED" ? "TED Europa" : "Öffentliche Vergabe"
}
