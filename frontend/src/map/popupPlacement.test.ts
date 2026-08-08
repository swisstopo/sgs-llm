import { describe, expect, it } from 'vitest';
import { popupPlacement } from './popupPlacement';

const MAP: [number, number] = [1000, 800];
const POPUP: [number, number] = [320, 300];

describe('popupPlacement', () => {
  it('opens above the click when there is room', () => {
    expect(popupPlacement([500, 600], MAP, POPUP)).toEqual({
      positioning: 'bottom-center',
      offset: [0, -12],
    });
  });

  it('flips below when the top edge would clip it', () => {
    expect(popupPlacement([500, 100], MAP, POPUP)).toEqual({
      positioning: 'top-center',
      offset: [0, 12],
    });
  });

  it('pins inward near the left and right edges', () => {
    expect(popupPlacement([20, 600], MAP, POPUP).positioning).toBe('bottom-left');
    expect(popupPlacement([980, 600], MAP, POPUP).positioning).toBe('bottom-right');
  });

  it('keeps the roomier side when it fits on neither', () => {
    const tall: [number, number] = [320, 900];
    expect(popupPlacement([500, 700], MAP, tall).positioning).toBe('bottom-center');
    expect(popupPlacement([500, 100], MAP, tall).positioning).toBe('top-center');
  });
});
