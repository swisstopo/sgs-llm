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
      background: #1f2d3d;
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
      background: rgb(255 255 255 / 0.25);
    }

    .wordmark {
      color: #ffffff;
      font-size: 1rem;
      font-weight: 600;
      letter-spacing: 0.06em;
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
        <img class="logo-sgs" src="/logos/sgs-white.png" alt="Strategie Geoinformation Schweiz" />
        <span class="divider"></span>
        <span class="wordmark">LLM</span>
      </div>
      <img class="logo-swisstopo" src="/logos/swisstopo-white.png" alt="swisstopo" />
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-header': SgsHeader;
  }
}
