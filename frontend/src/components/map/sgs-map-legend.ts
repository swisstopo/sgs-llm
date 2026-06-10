import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext } from '../../context';
import type { LayerService, MapLayerState, OfficialLayerState } from '../../services/LayerService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { chevronDownIcon, chevronUpIcon } from '../shell/icons';
import './sgs-legend-content';

/**
 * Legend overlay docked at the map's top-right. Shows the legend of every
 * visible official layer that has one, and removes itself when none do.
 */
@customElement('sgs-map-legend')
export class SgsMapLegend extends LitElement {
  static override styles = css`
    :host {
      display: block;
    }

    .card {
      background: var(--sgc-color-bg--white);
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      overflow: hidden;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      padding: 0.5rem 0.75rem;
      border-bottom: 1px solid var(--sgc-color-border);
      font-weight: 600;
      font-size: 0.875rem;
    }

    .collapse {
      display: grid;
      place-items: center;
      border: none;
      background: none;
      cursor: pointer;
      padding: 0;
      line-height: 0;
      color: var(--sgc-color-text--secondary);
    }

    .body {
      max-height: 60vh;
      overflow-y: auto;
      padding: 0.5rem 0.75rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }

    .layer-label {
      margin: 0 0 0.375rem;
      padding: 0.25rem 0.5rem;
      background: var(--sgc-color-bg--grey);
      border-left: 3px solid var(--sgc-color-brand);
      border-radius: 0.1875rem;
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--sgc-color-text);
    }

    sgs-legend-content {
      display: block;
      padding-left: 0.5rem;
    }
  `;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private collapsed = false;

  private layers?: ObservableController<MapLayerState[]>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.layers ??= new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const layers = this.layers?.value ?? this.layerService.layers;
    const legendLayers = layers.filter(
      (layer): layer is OfficialLayerState =>
        layer.visible && layer.kind === 'official' && layer.config.hasLegend,
    );
    if (legendLayers.length === 0) {
      return nothing;
    }
    return html`
      <div class="card">
        <header>
          <span>${t('layers.legend')}</span>
          <button
            class="collapse"
            aria-expanded=${!this.collapsed}
            aria-label=${t('layers.legend')}
            @click=${() => (this.collapsed = !this.collapsed)}
          >
            ${this.collapsed ? chevronDownIcon : chevronUpIcon}
          </button>
        </header>
        ${this.collapsed
          ? nothing
          : html`
              <div class="body">
                ${legendLayers.map(
                  (layer) => html`
                    <section>
                      <p class="layer-label">${layer.label}</p>
                      <sgs-legend-content .layerId=${layer.config.id}></sgs-legend-content>
                    </section>
                  `,
                )}
              </div>
            `}
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-map-legend': SgsMapLegend;
  }
}
