import { css } from 'lit';

/** Shared host chrome for the scrollable flyout panels (one source of padding). */
export const panelBaseStyles = css`
  :host {
    display: block;
    padding: 1rem;
    overflow-y: auto;
    min-height: 0;
  }
`;
