import { describe, expect, it } from 'vitest';
import { initialZoomForViewport } from './MapService';

describe('initialZoomForViewport', () => {
  it('uses the whole-country resolution when its tile matrix covers the viewport', () => {
    expect(initialZoomForViewport(900, 600)).toBe(1);
  });

  it('zooms in enough to remove grey strips on a wide desktop', () => {
    expect(initialZoomForViewport(1_600, 900)).toBe(2);
  });

  it('covers a tall mobile viewport as well as its width', () => {
    expect(initialZoomForViewport(360, 800)).toBe(2);
  });

  it('falls back safely while the target has no layout size', () => {
    expect(initialZoomForViewport(0, 0)).toBe(1);
  });
});
