import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('sgs-header')
export class SgsHeader extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0 1rem;
      height: 3.5rem;
      background: var(--sgc-color-bg--white, #ffffff);
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .title {
      font-size: 1.125rem;
      font-weight: 700;
    }

    .title .accent {
      color: var(--sgc-color-brand, #d8232a);
    }
  `;

  override render() {
    return html`<span class="title"><span class="accent">SGS</span> LLM</span>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-header': SgsHeader;
  }
}
