import { LitElement, css, html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { ProgressStep } from '../../services/ChatService';
import { checkIcon, closeIcon, dotIcon } from '../shell/icons';

/** Live tool-progress steps streamed while the agent works. */
@customElement('sgs-progress-steps')
export class SgsProgressSteps extends LitElement {
  static override styles = css`
    :host {
      display: block;
      font-size: 0.8125rem;
      color: var(--sgc-color-text--secondary);
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0.25rem;
    }

    li {
      display: flex;
      align-items: baseline;
      gap: 0.375rem;
    }

    .icon {
      flex: none;
      display: grid;
      place-items: center;
      line-height: 0;
    }

    .icon svg {
      width: 1rem;
      height: 1rem;
    }

    .icon[data-status='started'] {
      animation: pulse 1.2s ease-in-out infinite;
    }

    .icon[data-status='finished'] {
      color: #2e7d32;
    }

    .icon[data-status='failed'] {
      color: var(--sgc-color-brand);
    }

    .detail {
      display: block;
      font-size: 0.75rem;
      opacity: 0.8;
    }

    @keyframes pulse {
      50% {
        opacity: 0.3;
      }
    }
  `;

  @property({ attribute: false }) steps: ProgressStep[] = [];

  override render() {
    return html`
      <ul>
        ${this.steps.map(
          (step) => html`
            <li>
              <span class="icon" data-status=${step.status}>
                ${step.status === 'started'
                  ? dotIcon
                  : step.status === 'finished'
                    ? checkIcon
                    : closeIcon}
              </span>
              <span>
                ${step.label} ${step.detail ? html`<span class="detail">${step.detail}</span>` : ''}
              </span>
            </li>
          `,
        )}
      </ul>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-progress-steps': SgsProgressSteps;
  }
}
