import { css } from 'lit';

/**
 * Shared chrome for the "Displayed maps" panel: the card container, the
 * uppercase card header, and the row layout used by both the background-map
 * rows and the active layer rows so the two read as one coherent list.
 */
export const layerRowStyles = css`
  .card {
    border: 1px solid var(--sgc-color-border);
    border-radius: 0.5rem;
    background: var(--sgc-color-bg--white);
    overflow: hidden;
  }

  .card + .card {
    margin-top: 1rem;
  }

  .card-header {
    margin: 0;
    padding: 0.75rem 0.875rem 0.625rem;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--sgc-color-text--secondary);
    border-bottom: 1px solid var(--sgc-color-border);
  }

  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.625rem;
    font-size: 0.875rem;
  }

  .row + .row {
    border-top: 1px solid var(--sgc-color-border--subtle);
  }

  .row:hover {
    background: var(--sgc-color-bg--grey);
  }

  .row .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row[data-hidden] .name {
    color: var(--sgc-color-text--disabled);
    text-decoration: line-through;
  }

  .icon-btn {
    flex: none;
    display: grid;
    place-items: center;
    border: none;
    background: none;
    cursor: pointer;
    padding: 0.25rem;
    border-radius: 0.25rem;
    color: var(--sgc-color-text--secondary);
    line-height: 0;
  }

  .icon-btn:hover:not(:disabled) {
    background: rgb(0 0 0 / 0.06);
    color: var(--sgc-color-text);
  }

  .icon-btn:disabled {
    color: var(--sgc-color-text--disabled);
    cursor: default;
  }

  .icon-btn.eye {
    color: var(--sgc-color-text);
  }

  .row[data-hidden] .icon-btn.eye {
    color: var(--sgc-color-text--disabled);
  }
`;
