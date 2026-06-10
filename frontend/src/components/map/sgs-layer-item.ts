import { LitElement, css, html, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext } from '../../context';
import type { LayerService, MapLayerState } from '../../services/LayerService';
import { t } from '../../i18n/i18n';
import { layerRowStyles } from './layerRowStyles';
import {
  chevronDownIcon,
  chevronUpIcon,
  eyeClosedIcon,
  eyeOpenIcon,
  legendIcon,
  removeIcon,
  zoomToIcon,
} from '../shell/icons';

/** One active layer row: visibility, opacity, reorder, zoom, legend, remove. */
@customElement('sgs-layer-item')
export class SgsLayerItem extends LitElement {
  static override styles = [
    layerRowStyles,
    css`
      :host {
        display: block;
      }

      .opacity {
        display: flex;
        padding: 0 0.625rem 0.5rem 2.5rem;
      }

      input[type='range'] {
        flex: 1;
        accent-color: var(--sgc-color-brand);
      }
    `,
  ];

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @property({ attribute: false }) layer!: MapLayerState;
  @property({ type: Boolean }) isFirst = false;
  @property({ type: Boolean }) isLast = false;

  private showLegend(): void {
    this.dispatchEvent(
      new CustomEvent('sgs-show-legend', {
        detail: { layerId: this.layer.id, label: this.layer.label },
        bubbles: true,
        composed: true,
      }),
    );
  }

  override render() {
    const { layer } = this;
    const canZoom = this.layerService.getZoomBBox(layer.id) !== undefined;
    const hasLegend = layer.kind === 'official' && layer.config.hasLegend;
    return html`
      <div class="row" ?data-hidden=${!layer.visible}>
        <button
          class="icon-btn eye"
          aria-pressed=${layer.visible}
          title=${t('layers.toggle')}
          aria-label=${t('layers.toggle')}
          @click=${() => this.layerService.setVisible(layer.id, !layer.visible)}
        >
          ${layer.visible ? eyeOpenIcon : eyeClosedIcon}
        </button>
        <span class="name" title=${layer.label}>${layer.label}</span>
        ${canZoom
          ? html`
              <button
                class="icon-btn"
                title=${t('layers.zoomTo')}
                aria-label=${t('layers.zoomTo')}
                @click=${() => this.layerService.zoomToLayer(layer.id)}
              >
                ${zoomToIcon}
              </button>
            `
          : nothing}
        ${hasLegend
          ? html`
              <button
                class="icon-btn"
                title=${t('layers.legend')}
                aria-label=${t('layers.legend')}
                @click=${() => this.showLegend()}
              >
                ${legendIcon}
              </button>
            `
          : nothing}
        <button
          class="icon-btn"
          title=${t('layers.moveUp')}
          aria-label=${t('layers.moveUp')}
          ?disabled=${this.isFirst}
          @click=${() => this.layerService.moveLayer(layer.id, 'up')}
        >
          ${chevronUpIcon}
        </button>
        <button
          class="icon-btn"
          title=${t('layers.moveDown')}
          aria-label=${t('layers.moveDown')}
          ?disabled=${this.isLast}
          @click=${() => this.layerService.moveLayer(layer.id, 'down')}
        >
          ${chevronDownIcon}
        </button>
        <button
          class="icon-btn"
          title=${t('layers.remove')}
          aria-label=${t('layers.remove')}
          @click=${() => this.layerService.removeLayer(layer.id)}
        >
          ${removeIcon}
        </button>
      </div>
      <div class="opacity">
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          .value=${String(layer.opacity)}
          aria-label=${t('layers.opacity')}
          @input=${(e: Event) =>
            this.layerService.setOpacity(layer.id, Number((e.target as HTMLInputElement).value))}
        />
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-item': SgsLayerItem;
  }
}
