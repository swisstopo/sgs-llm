import { beforeAll, describe, expect, it } from 'vitest';
import { fromLonLat } from 'ol/proj';
import { formatLV95, registerProjections } from './projection';

beforeAll(() => {
  registerProjections();
});

describe('formatLV95', () => {
  it('formats a Web Mercator coordinate as an LV95 string near the project origin', () => {
    // Bern (~7.4386, 46.9511) is close to the LV95 origin 2600000 / 1200000.
    const formatted = formatLV95(fromLonLat([7.438632, 46.951083]) as [number, number]);
    expect(formatted).toMatch(/2'\d{3}'\d{3}, 1'\d{3}'\d{3}/);
  });
});
