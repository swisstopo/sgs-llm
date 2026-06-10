import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('sgs-header')
export class SgsHeader extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: 0.875rem;
      padding: 0 1rem;
      height: 3.5rem;
      background: var(--sgc-color-bg--white, #ffffff);
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }

    .logo-sgs {
      height: 2.25rem;
      width: auto;
    }

    .divider {
      width: 1px;
      height: 1.5rem;
      background: var(--sgc-color-border, #d5dbe0);
    }

    .wordmark {
      font-size: 1.0625rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      color: var(--sgc-color-brand, #d8232a);
    }

    .logo-swisstopo {
      height: 2rem;
      width: auto;
      margin-left: auto;
    }
  `;

  override render() {
    return html`
      <div class="brand">
        <img class="logo-sgs" src="/logos/sgs-dark.png" alt="Strategie Geoinformation Schweiz" />
        <span class="divider"></span>
        <span class="wordmark">LLM</span>
      </div>
      <img class="logo-swisstopo" src="/logos/swisstopo-dark.png" alt="swisstopo" />
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-header': SgsHeader;
  }
}
