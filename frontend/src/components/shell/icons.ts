import { html, svg } from 'lit';
import type { SVGTemplateResult, TemplateResult } from 'lit';

/**
 * Inline SVG icons (24px grid, stroked).
 *
 * The icon body is built with Lit's `svg` tag so its children are created in
 * the SVG namespace; a plain `html` fragment would be parsed in the HTML
 * namespace and the shapes would never render.
 */
function icon(body: SVGTemplateResult, size = 22): TemplateResult {
  return html`<svg
    viewBox="0 0 24 24"
    width=${size}
    height=${size}
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    ${body}
  </svg>`;
}

// --- Navigation rail ---------------------------------------------------------

export const searchIcon = icon(svg`<circle cx="10" cy="10" r="7" /><path d="M15 15l6 6" />`);

export const mapsIcon = icon(
  svg`<path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z" /><path d="M9 4v13.5M15 6.5V20" />`,
);

export const catalogIcon = icon(
  svg`<path d="M12 3l9 4.5-9 4.5-9-4.5z" /><path d="M3 12l9 4.5 9-4.5" /><path d="M3 16.5 12 21l9-4.5" />`,
);

export const chatIcon = icon(svg`<path d="M3 4.5h18v12H9l-6 5z" />`);

export const feedbackIcon = icon(
  svg`<path d="M3 4.5h18v12H9l-6 5z" /><path d="M12 13.6l-2.4-2.2c-.9-.8-.8-2.1.1-2.7.8-.5 1.8-.3 2.3.5.5-.8 1.5-1 2.3-.5.9.6 1 1.9.1 2.7z" />`,
);

export const aboutIcon = icon(
  svg`<circle cx="12" cy="12" r="9" /><path d="M9.6 9.3a2.5 2.5 0 014.9.7c0 1.7-2.5 2-2.5 3.8" /><circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />`,
);

// "Translate" glyph (文A). Filled, so it is built directly rather than via
// the stroked icon() helper. The viewBox is inset with padding so the solid
// glyph renders at the same optical size as the outline rail icons.
// Path from Material Symbols (Apache-2.0).
export const languageIcon = html`<svg
  viewBox="-3.5 -3.5 31 31"
  width="22"
  height="22"
  fill="currentColor"
  aria-hidden="true"
>
  <path
    d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"
  />
</svg>`;

export const collapseIcon = icon(
  svg`<rect x="4" y="4" width="16" height="16" rx="2" /><path d="M10 4v16" /><path d="M16 10l-2.5 2 2.5 2" />`,
  20,
);

// --- Map / layer rows (shared by displayed-maps and layer-item) --------------

export const eyeOpenIcon = icon(
  svg`<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" />`,
  20,
);

export const eyeClosedIcon = icon(
  svg`<path d="M2.5 12S6 5.5 12 5.5c1.7 0 3.2.5 4.5 1.2M21.5 12S18 18.5 12 18.5c-1.7 0-3.2-.5-4.5-1.2" /><path d="M4 20 20 4" />`,
  20,
);

export const zoomToIcon = icon(
  svg`<circle cx="12" cy="12" r="7" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />`,
  18,
);

export const legendIcon = icon(
  svg`<circle cx="5" cy="7" r="1.2" /><circle cx="5" cy="12" r="1.2" /><circle cx="5" cy="17" r="1.2" /><path d="M9 7h11M9 12h11M9 17h11" />`,
  18,
);

export const removeIcon = icon(svg`<path d="M6 6l12 12M18 6 6 18" />`, 18);

/** Crosshair/target for the geolocate button. */
export const locateIcon = icon(
  svg`<circle cx="12" cy="12" r="7" /><path d="M12 1.5V5M12 19v3.5M1.5 12H5M19 12h3.5" /><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />`,
  24,
);

export const zoomInIcon = icon(svg`<path d="M12 5v14M5 12h14" />`, 24);

export const zoomOutIcon = icon(svg`<path d="M5 12h14" />`, 24);

export const infoIcon = icon(
  svg`<circle cx="12" cy="12" r="9" /><path d="M12 11v5.5" /><circle cx="12" cy="7.5" r="0.6" fill="currentColor" stroke="none" />`,
  18,
);

/** Six-dot grip for drag-reorder handles. */
export const gripIcon = icon(
  svg`<g fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.3" /><circle cx="15" cy="6" r="1.3" /><circle cx="9" cy="12" r="1.3" /><circle cx="15" cy="12" r="1.3" /><circle cx="9" cy="18" r="1.3" /><circle cx="15" cy="18" r="1.3" /></g>`,
  16,
);

/** Close (reuses the cross). */
export const closeIcon = removeIcon;

export const chevronUpIcon = icon(svg`<path d="M6 14l6-6 6 6" />`, 18);

export const chevronDownIcon = icon(svg`<path d="M6 10l6 6 6-6" />`, 18);

/** Collapsed-folder twisty (CSS rotates it 90° when open). */
export const chevronRightIcon = icon(svg`<path d="M9 6l6 6-6 6" />`, 16);

export const plusIcon = icon(svg`<path d="M12 5v14M5 12h14" />`, 18);

export const checkIcon = icon(svg`<path d="M5 12.5l4.5 4.5L19 7" />`, 18);

/** Small ring for an in-progress step. */
export const dotIcon = icon(svg`<circle cx="12" cy="12" r="5.5" />`, 16);
