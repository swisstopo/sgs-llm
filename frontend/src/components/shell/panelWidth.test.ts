import { describe, expect, it } from 'vitest';
import { MIN_PANEL_WIDTH, clampPanelWidth, panelWidthFromPointer } from './panelWidth';

describe('clampPanelWidth', () => {
  it('passes through widths within range', () => {
    expect(clampPanelWidth(500, 1500)).toBe(500);
  });

  it('clamps to the minimum', () => {
    expect(clampPanelWidth(100, 1500)).toBe(MIN_PANEL_WIDTH);
    expect(clampPanelWidth(-50, 1500)).toBe(MIN_PANEL_WIDTH);
  });

  it('clamps to the maximum, leaving a map strip', () => {
    // Wide viewport: hard cap at 768.
    expect(clampPanelWidth(2000, 1920)).toBe(768);
    // Narrow viewport: 1000 - 56 (rail) - 280 (map strip) = 664.
    expect(clampPanelWidth(2000, 1000)).toBe(664);
  });

  it('keeps the minimum on very narrow viewports', () => {
    expect(clampPanelWidth(500, 500)).toBe(MIN_PANEL_WIDTH);
  });

  it('rounds fractional widths', () => {
    expect(clampPanelWidth(420.6, 1500)).toBe(421);
  });
});

describe('panelWidthFromPointer', () => {
  it('subtracts the rail width from the pointer position', () => {
    expect(panelWidthFromPointer(556, 1500)).toBe(500);
  });

  it('clamps like clampPanelWidth', () => {
    expect(panelWidthFromPointer(0, 1500)).toBe(MIN_PANEL_WIDTH);
    expect(panelWidthFromPointer(5000, 1920)).toBe(768);
  });
});
