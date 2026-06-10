import { html } from 'lit';
import type { TemplateResult } from 'lit';

/**
 * Inline SVG icons for the navigation rail (24px grid, stroked, drawn fresh
 * for this project in the style of the SwissGeo rail icons).
 */
function icon(paths: TemplateResult): TemplateResult {
  return html`
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      ${paths}
    </svg>
  `;
}

export const searchIcon = icon(html`
  <circle cx="11" cy="11" r="6.5"></circle>
  <path d="M16 16l4.5 4.5"></path>
`);

export const mapsIcon = icon(html`
  <path d="M3 6.5L9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z"></path>
  <path d="M9 4v13.5M15 6.5V20"></path>
`);

export const catalogIcon = icon(html`
  <path d="M12 3l9 4.5-9 4.5-9-4.5z"></path>
  <path d="M3 12l9 4.5 9-4.5"></path>
  <path d="M3 16.5L12 21l9-4.5"></path>
`);

export const chatIcon = icon(html` <path d="M4 5h16v11H9l-5 4z"></path> `);

export const feedbackIcon = icon(html`
  <path d="M4 5h16v11H9l-5 4z"></path>
  <path
    d="M12 8.2c.9-1.4 3-1.2 3.4.4.3 1.2-.9 2-1.9 2.7l-1.5 1.1-1.5-1.1c-1-.7-2.2-1.5-1.9-2.7.4-1.6 2.5-1.8 3.4-.4z"
    fill="currentColor"
    stroke="none"
  ></path>
`);

export const aboutIcon = icon(html`
  <circle cx="12" cy="12" r="9"></circle>
  <path d="M9.8 9.5a2.3 2.3 0 113.6 1.9c-.8.6-1.4 1-1.4 2.1"></path>
  <circle cx="12" cy="16.8" r="0.4" fill="currentColor" stroke="none"></circle>
`);

export const languageIcon = icon(html`
  <circle cx="12" cy="12" r="9"></circle>
  <path
    d="M3 12h18M12 3c2.5 2.3 3.8 5.4 3.8 9S14.5 18.7 12 21c-2.5-2.3-3.8-5.4-3.8-9S9.5 5.3 12 3z"
  ></path>
`);

export const collapseIcon = icon(html`
  <rect x="4" y="4" width="16" height="16" rx="2"></rect>
  <path d="M10 4v16"></path>
  <path d="M16 10l-2.5 2 2.5 2"></path>
`);
