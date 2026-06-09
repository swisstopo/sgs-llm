import { LitElement, css, html } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext } from '../../context';
import type { LayerService, OfficialLayerState } from '../../services/LayerService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import '../search/sgs-search-panel';
import './sgs-catalog-tree';
import './sgs-layer-item';

type PanelTab = 'search' | 'catalog' | 'layers';

/** Floating panel over the map: search, curated catalog, active layers. */
@customElement('sgs-layer-panel')
export class SgsLayerPanel extends LitElement {
  static override styles = css`
    :host {
      position: absolute;
      top: 0.75rem;
      right: 0.75rem;
      z-index: 1;
      width: 21rem;
      max-width: calc(100vw - 2rem);
      display: block;
      background: var(--sgc-color-bg--white, #ffffff);
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.375rem;
      box-shadow: 0 2px 8px rgb(0 0 0 / 0.15);
      font-size: 0.875rem;
    }

    nav {
      display: flex;
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    nav button {
      flex: 1;
      border: none;
      background: none;
      font: inherit;
      font-size: 0.875rem;
      padding: 0.625rem 0.5rem;
      cursor: pointer;
      color: var(--sgc-color-text--secondary, #4b5a68);
      border-bottom: 2px solid transparent;
    }

    nav button[aria-selected='true'] {
      color: var(--sgc-color-brand, #d8232a);
      border-bottom-color: var(--sgc-color-brand, #d8232a);
      font-weight: 600;
    }

    .tab-content {
      padding: 0.75rem;
      max-height: min(26rem, 60vh);
      overflow-y: auto;
    }

    .empty {
      margin: 0;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .count {
      font-size: 0.6875rem;
      background: var(--sgc-color-brand, #d8232a);
      color: #fff;
      border-radius: 999px;
      padding: 0 0.375rem;
      margin-left: 0.25rem;
    }
  `;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private tab: PanelTab = 'search';

  private layers?: ObservableController<OfficialLayerState[]>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.layers ??= new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const layers = this.layers?.value ?? [];
    return html`
      <nav role="tablist">
        ${(['search', 'catalog', 'layers'] as const).map(
          (tab) => html`
            <button role="tab" aria-selected=${this.tab === tab} @click=${() => (this.tab = tab)}>
              ${t(`panel.${tab}`)}
              ${tab === 'layers' && layers.length > 0
                ? html`<span class="count">${layers.length}</span>`
                : ''}
            </button>
          `,
        )}
      </nav>
      <div class="tab-content">${this.renderTab(layers)}</div>
    `;
  }

  private renderTab(layers: OfficialLayerState[]) {
    switch (this.tab) {
      case 'search':
        return html`<sgs-search-panel></sgs-search-panel>`;
      case 'catalog':
        return html`<sgs-catalog-tree></sgs-catalog-tree>`;
      case 'layers':
        return layers.length === 0
          ? html`<p class="empty">${t('layers.empty')}</p>`
          : layers.map(
              (layer, index) => html`
                <sgs-layer-item
                  .layer=${layer}
                  ?isFirst=${index === 0}
                  ?isLast=${index === layers.length - 1}
                ></sgs-layer-item>
              `,
            );
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-panel': SgsLayerPanel;
  }
}
