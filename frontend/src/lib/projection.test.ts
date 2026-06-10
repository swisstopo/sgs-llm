import { beforeAll, describe, expect, it } from 'vitest';
import {
  bboxLV95To4326,
  bboxToLV95,
  lonLatToLV95,
  lv95ToLonLat,
  registerProjections,
} from './projection';

beforeAll(() => {
  registerProjections();
});

describe('LV95 conversions', () => {
  it('converts Bern lon/lat to LV95 (project origin ~2600000/1200000)', () => {
    const [east, north] = lonLatToLV95([7.438632, 46.951083]);
    expect(east).toBeCloseTo(2600000, -2);
    expect(north).toBeCloseTo(1200000, -2);
  });

  it('round-trips through both directions', () => {
    const [lon, lat] = lv95ToLonLat(lonLatToLV95([8.2318, 46.8131]));
    expect(lon).toBeCloseTo(8.2318, 5);
    expect(lat).toBeCloseTo(46.8131, 5);
  });

  it('round-trips bboxes', () => {
    const bbox: [number, number, number, number] = [7.0, 46.2, 8.0, 47.0];
    const roundTripped = bboxLV95To4326(bboxToLV95(bbox));
    roundTripped.forEach((value, i) => expect(value).toBeCloseTo(bbox[i]!, 4));
  });
});
