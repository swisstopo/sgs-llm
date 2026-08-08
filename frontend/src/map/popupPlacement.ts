/**
 * Keeping the identify popup on screen.
 *
 * ol/Overlay pins an element to a map coordinate and leaves it there, half off the canvas
 * if that is where it lands. This picks which corner of the popup to pin, so it opens
 * above the click when there is room and below it when the top edge would clip it.
 */

/** The subset of ol/Overlay's positioning values this uses: vertical side + horizontal. */
export type Positioning =
  | 'bottom-center'
  | 'bottom-left'
  | 'bottom-right'
  | 'top-center'
  | 'top-left'
  | 'top-right';

/** Gap between the click point and the nearest popup edge, px. */
const GAP = 12;

export interface Placement {
  positioning: Positioning;
  offset: [number, number];
}

/**
 * Where to pin a popup of `popupSize` opened at `pixel` on a map of `mapSize`, all px.
 */
export function popupPlacement(
  pixel: [number, number],
  mapSize: [number, number],
  popupSize: [number, number],
): Placement {
  const [x, y] = pixel;
  const [mapWidth, mapHeight] = mapSize;
  const [width, height] = popupSize;

  // Above by default, because a popup below the cursor covers what was just clicked.
  // Below when it would not fit above - and when it fits neither, whichever side clips
  // less, so a popup taller than the map still shows its header.
  const roomAbove = y - GAP;
  const roomBelow = mapHeight - y - GAP;
  const above = height <= roomAbove || roomAbove >= roomBelow;

  // Centred unless a side overflows, then pin that corner so the popup opens inward:
  // `bottom-left` puts its bottom-left corner on the click, extending up and right.
  const half = width / 2;
  const horizontal = x - half < 0 ? 'left' : x + half > mapWidth ? 'right' : 'center';

  return {
    positioning: `${above ? 'bottom' : 'top'}-${horizontal}` as Positioning,
    offset: [0, above ? -GAP : GAP],
  };
}
