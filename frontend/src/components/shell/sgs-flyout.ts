import { LitElement, css, html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { uiServiceContext } from '../../context';
import type { UiService } from '../../services/UiService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { collapseIcon } from './icons';

/**
 * Flyout panel chrome next to the navigation rail: title bar with a
 * collapse button, optional header extras (slot "header-extra"), and a
 * scrollable body (default slot).
 */
@customElement('sgs-flyout')
export class SgsFlyout extends LitElement {
  static override styles = css`
    :host {
      display: grid;
      grid-template-rows: auto 1fr;
      height: 100%;
      min-height: 0;
      background: var(--sgc-color-bg--white);
      border-right: 1px solid var(--sgc-color-border);
      box-shadow: 2px 0 6px rgb(0 0 0 / 0.06);
    }

    header {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--sgc-color-border);
      background: var(--sgc-color-bg--grey);
    }

    h2 {
      flex: 1;
      margin: 0;
      font-size: 1rem;
      font-weight: 600;
    }

    .collapse {
      display: grid;
      place-items: center;
      border: none;
      background: none;
      cursor: pointer;
      padding: 0.25rem;
      border-radius: 0.25rem;
      color: var(--sgc-color-text--secondary);
    }

    .collapse:hover {
      background: var(--sgc-color-bg--grey);
      color: var(--sgc-color-text);
    }

    .body {
      min-height: 0;
      overflow: hidden;
      display: grid;
    }
  `;

  @consume({ context: uiServiceContext })
  private uiService!: UiService;

  @property() heading = '';

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <header>
        <h2>${this.heading}</h2>
        <slot name="header-extra"></slot>
        <button
          class="collapse"
          title=${t('panel.close')}
          aria-label=${t('panel.close')}
          @click=${() => this.uiService.closePanel()}
        >
          ${collapseIcon}
        </button>
      </header>
      <div class="body"><slot></slot></div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-flyout': SgsFlyout;
  }
}
