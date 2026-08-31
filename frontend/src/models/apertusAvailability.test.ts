import { describe, expect, it } from 'vitest';
import { isApertusAvailable } from './apertusAvailability';

describe('isApertusAvailable', () => {
  it('waits for the weekday cold start and closes at 19:00 Zurich time', () => {
    // CEST is UTC+2 on 31 August 2026.
    expect(isApertusAvailable(new Date('2026-08-31T04:39:00Z'))).toBe(false);
    expect(isApertusAvailable(new Date('2026-08-31T04:40:00Z'))).toBe(true);
    expect(isApertusAvailable(new Date('2026-08-31T16:59:59Z'))).toBe(true);
    expect(isApertusAvailable(new Date('2026-08-31T17:00:00Z'))).toBe(false);
  });

  it('stays unavailable throughout the weekend', () => {
    expect(isApertusAvailable(new Date('2026-08-29T10:00:00Z'))).toBe(false);
    expect(isApertusAvailable(new Date('2026-08-30T10:00:00Z'))).toBe(false);
  });

  it('uses Europe/Zurich rather than a fixed UTC offset', () => {
    // CET is UTC+1 in December; this is 06:40 in Zurich.
    expect(isApertusAvailable(new Date('2026-12-07T05:40:00Z'))).toBe(true);
  });

  it('treats an invalid clock value as unavailable', () => {
    expect(isApertusAvailable(new Date('invalid'))).toBe(false);
  });
});
