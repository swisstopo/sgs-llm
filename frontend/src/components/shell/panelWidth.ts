/** Width of the navigation rail in px (3.5rem in the shell grid). */
const RAIL_WIDTH = 56;

/** Narrowest useful panel. */
export const MIN_PANEL_WIDTH = 320;

/** Widest panel; always leaves a usable strip of map beside it. */
const MAX_PANEL_WIDTH = 768;
const MIN_MAP_STRIP = 280;

export const PANEL_WIDTH_STORAGE_KEY = 'sgs-llm.panelWidth';

/** Clamps a desired flyout width (px) against the viewport. */
export function clampPanelWidth(width: number, viewportWidth: number): number {
  const max = Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, viewportWidth - RAIL_WIDTH - MIN_MAP_STRIP));
  return Math.round(Math.max(MIN_PANEL_WIDTH, Math.min(max, width)));
}

/** Panel width from a drag position (pointer clientX), clamped. */
export function panelWidthFromPointer(clientX: number, viewportWidth: number): number {
  return clampPanelWidth(clientX - RAIL_WIDTH, viewportWidth);
}
