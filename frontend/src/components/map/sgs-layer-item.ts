import { LitElement, css, html, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext, uiServiceContext } from '../../context';
import type { LayerService, MapLayerState } from '../../services/LayerService';
import type { UiService } from '../../services/UiService';
import { t } from '../../i18n/i18n';
import { layerRowStyles } from './layerRowStyles';
import {
  chevronDownIcon,
  chevronUpIcon,
  eyeClosedIcon,
  eyeOpenIcon,
  gripIcon,
  infoIcon,
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

      .drag-handle {
        flex: none;
        cursor: grab;
        color: var(--sgc-color-text--disabled);
        line-height: 0;
        touch-action: none;
      }

      .drag-handle:active {
        cursor: grabbing;
      }
    `,
  ];

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @consume({ context: uiServiceContext })
  private uiService!: UiService;

  @property({ attribute: false }) layer!: MapLayerState;
  @property({ type: Boolean }) isFirst = false;
  @property({ type: Boolean }) isLast = false;

  override render() {
    const { layer } = this;
    const canZoom = this.layerService.canZoomTo(layer.id);
    return html`
      <div class="row" ?data-hidden=${!layer.visible}>
        <span
          class="drag-handle"
          draggable="true"
          title=${t('layers.dragToReorder')}
          aria-hidden="true"
        >
          ${gripIcon}
        </span>
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
        ${layer.kind === 'official'
          ? html`
              <button
                class="icon-btn"
                title=${t('layers.info')}
                aria-label=${t('layers.info')}
                @click=${() => this.uiService.openLayerInfo({ id: layer.id, label: layer.label })}
              >
                ${infoIcon}
              </button>
            `
          : nothing}
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
