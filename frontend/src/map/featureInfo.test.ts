import { describe, expect, it } from 'vitest';
import { MAX_PROPERTY_ROWS, displayProperties, featureLabel, formatValue } from './featureInfo';

describe('featureLabel', () => {
  it('prefers the conventional label keys in order', () => {
    expect(featureLabel({ name: 'Bern', label: 'Stadt Bern' }, 'x')).toBe('Stadt Bern');
    expect(featureLabel({ gemname: 'Köniz', name: '' }, 'x')).toBe('Köniz');
  });

  it('falls back to the first non-empty string property', () => {
    expect(featureLabel({ id: 42, kategorie: 'Wald' }, 'x')).toBe('Wald');
  });

  it('uses the fallback when nothing names the feature', () => {
    expect(featureLabel({ area_m2: 1200 }, 'Feature')).toBe('Feature');
    expect(featureLabel({}, 'Feature')).toBe('Feature');
  });

  it('ignores geometry, which is a property but not a name', () => {
    expect(featureLabel({ geometry: 'POLYGON(...)' }, 'Feature')).toBe('Feature');
  });
});

describe('formatValue', () => {
  it('rounds floats and leaves integers alone', () => {
    // `compute` returns raw areas; ten digits of float noise is not information.
    expect(formatValue(1234567.891234)).toBe('1234567.89');
    expect(formatValue(42)).toBe('42');
  });

  it('renders arrays and objects readably', () => {
    expect(formatValue(['a', 'b'])).toBe('a, b');
    expect(formatValue({ a: 1 })).toBe('{"a":1}');
  });
});

describe('displayProperties', () => {
  it('drops geometry and empty values, keeps computed fields', () => {
    expect(
      displayProperties({ geometry: {}, name: 'Bern', empty: '', missing: null, area_m2: 1.5 }),
    ).toEqual([
      ['name', 'Bern'],
      ['area_m2', '1.50'],
    ]);
  });

  it('hides renderer internals without hiding ordinary id and bbox-named properties', () => {
    expect(
      displayProperties({
        __feature_id: 7,
        __sgs_covering: { xmin: 1, ymin: 2, xmax: 3, ymax: 4 },
        geometry: 'WKB',
        road_id: 'H21',
        bbox_note: 'surveyed',
      }),
    ).toEqual([
      ['road_id', 'H21'],
      ['bbox_note', 'surveyed'],
    ]);
  });

  it('caps the row count', () => {
    const many = Object.fromEntries(
      Array.from({ length: MAX_PROPERTY_ROWS + 5 }, (_, i) => [`k${i}`, i + 1]),
    );
    expect(displayProperties(many)).toHaveLength(MAX_PROPERTY_ROWS);
  });
});
