import { beforeAll, describe, expect, it } from 'vitest';
import { transform } from 'ol/proj';
import { formatLV95, lonLatToLV95InBounds, registerProjections } from './projection';

beforeAll(() => {
  registerProjections();
});

describe('formatLV95', () => {
  it('formats an LV95 map coordinate with thousands separators', () => {
    expect(formatLV95([2600000, 1199999.6])).toBe("2'600'000, 1'200'000");
  });

  it('matches the WGS84 → LV95 transform for Bern', () => {
    // Bern (~7.4386, 46.9511) is close to the LV95 origin 2600000 / 1200000.
    const bern = transform([7.438632, 46.951083], 'EPSG:4326', 'EPSG:2056');
    expect(formatLV95(bern as [number, number])).toMatch(/2'\d{3}'\d{3}, 1'\d{3}'\d{3}/);
  });
});

describe('lonLatToLV95InBounds', () => {
  it('transforms Swiss positions into LV95', () => {
    // The old Bern observatory is the LV95 origin, 2600000 / 1200000.
    const bern = lonLatToLV95InBounds([7.438632, 46.951083]);
    expect(bern?.[0]).toBeCloseTo(2600000, -2);
    expect(bern?.[1]).toBeCloseTo(1200000, -2);
    expect(lonLatToLV95InBounds([8.55, 47.37])).toBeDefined(); // Zurich
  });

  it('rejects positions outside the LV95 map extent', () => {
    expect(lonLatToLV95InBounds([2.35, 48.85])).toBeUndefined(); // Paris
    expect(lonLatToLV95InBounds([13.4, 52.5])).toBeUndefined(); // Berlin
  });
});
