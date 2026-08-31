/** Apertus's user-facing service window (docs/apertus-endpoint.md). */
export const APERTUS_TIMEZONE = 'Europe/Zurich';
export const APERTUS_READY_MINUTE = 6 * 60 + 40;
export const APERTUS_STOP_MINUTE = 19 * 60;

const WEEKDAYS = new Set(['Mon', 'Tue', 'Wed', 'Thu', 'Fri']);
const zurichClock = new Intl.DateTimeFormat('en-US', {
  timeZone: APERTUS_TIMEZONE,
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/**
 * Whether the scheduled Apertus instance should be ready to accept a turn.
 *
 * EC2 starts at 06:30, but measured cold start is about five minutes, so the UI
 * waits until 06:40 before enabling the model. The backend remains authoritative:
 * a failed morning start is still reported as `model_unavailable`.
 */
export function isApertusAvailable(at: Date = new Date()): boolean {
  if (!Number.isFinite(at.getTime())) {
    return false;
  }

  const parts = Object.fromEntries(
    zurichClock
      .formatToParts(at)
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value]),
  );
  if (!WEEKDAYS.has(parts.weekday ?? '')) {
    return false;
  }

  const hour = Number(parts.hour);
  const minute = Number(parts.minute);
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) {
    return false;
  }
  const localMinute = hour * 60 + minute;
  return localMinute >= APERTUS_READY_MINUTE && localMinute < APERTUS_STOP_MINUTE;
}
