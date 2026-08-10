import { LitElement, css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext, uiServiceContext } from '../../context';
import type { DataLayerState, LayerService, MapLayerState } from '../../services/LayerService';
import type { UiService } from '../../services/UiService';
import type { StyleHint } from '../../protocol/v1';
import { resolveStyle } from '../../map/dataLayerStyle';
import { t } from '../../i18n/i18n';
import { layerRowStyles } from './layerRowStyles';
import {
  chevronDownIcon,
  chevronUpIcon,
  eyeClosedIcon,
  eyeOpenIcon,
  gripIcon,
  infoIcon,
  paletteIcon,
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

      .style {
        display: grid;
        grid-template-columns: auto 1fr;
        align-items: center;
        gap: 0.375rem 0.625rem;
        padding: 0 0.625rem 0.625rem 2.5rem;
        font-size: 0.75rem;
        color: var(--sgc-color-text--secondary);
      }

      .style input[type='color'] {
        justify-self: start;
        width: 2.5rem;
        height: 1.5rem;
        padding: 0;
        border: 1px solid var(--sgc-color-border);
        border-radius: 0.25rem;
        background: none;
        cursor: pointer;
      }

      .style .slider {
        display: flex;
        align-items: center;
        gap: 0.5rem;
      }

      .style .value {
        min-width: 1.75rem;
        text-align: right;
        font-variant-numeric: tabular-nums;
      }

      .icon-btn[aria-pressed='true'] {
        background: rgb(0 0 0 / 0.06);
        color: var(--sgc-color-text);
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

  @state() private styleOpen = false;

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
        ${layer.kind === 'data'
          ? html`
              <button
                class="icon-btn"
                aria-pressed=${this.styleOpen}
                title=${t('layers.style')}
                aria-label=${t('layers.style')}
                @click=${() => (this.styleOpen = !this.styleOpen)}
              >
                ${paletteIcon}
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
      ${layer.kind === 'data' && this.styleOpen ? this.renderStyle(layer) : nothing}
    `;
  }

  /**
   * Symbology for chat data layers only: official WMTS/WMS overlays are
   * rendered by swisstopo's servers, where opacity is the only knob we have.
   */
  private renderStyle(layer: DataLayerState) {
    const style = resolveStyle(layer.spec);
    const isPoint = layer.spec.geometry_type === 'point';
    const isLine = layer.spec.geometry_type === 'line';
    const set = (hint: StyleHint) => this.layerService.setStyle(layer.id, hint);
    return html`
      <div class="style">
        ${isLine
          ? nothing
          : html`
              <label for="fill-${layer.id}">${t('layers.fillColor')}</label>
              <input
                id="fill-${layer.id}"
                type="color"
                .value=${style.fillColor}
                @input=${(e: Event) => set({ fill_color: (e.target as HTMLInputElement).value })}
              />
            `}
        <label for="stroke-${layer.id}">${t('layers.strokeColor')}</label>
        <input
          id="stroke-${layer.id}"
          type="color"
          .value=${style.strokeColor}
          @input=${(e: Event) => set({ stroke_color: (e.target as HTMLInputElement).value })}
        />
        <label for="width-${layer.id}">${t('layers.strokeWidth')}</label>
        <span class="slider">
          <input
            id="width-${layer.id}"
            type="range"
            min="0"
            max="10"
            step="0.5"
            .value=${String(style.strokeWidth)}
            @input=${(e: Event) =>
              set({ stroke_width: Number((e.target as HTMLInputElement).value) })}
          />
          <span class="value">${style.strokeWidth}</span>
        </span>
        ${isPoint
          ? html`
              <label for="radius-${layer.id}">${t('layers.pointRadius')}</label>
              <span class="slider">
                <input
                  id="radius-${layer.id}"
                  type="range"
                  min="1"
                  max="20"
                  step="1"
                  .value=${String(style.pointRadius)}
                  @input=${(e: Event) =>
                    set({ point_radius: Number((e.target as HTMLInputElement).value) })}
                />
                <span class="value">${style.pointRadius}</span>
              </span>
            `
          : nothing}
        <label for="fillopacity-${layer.id}">${t('layers.fillOpacity')}</label>
        <span class="slider">
          <input
            id="fillopacity-${layer.id}"
            type="range"
            min="0"
            max="1"
            step="0.05"
            .value=${String(style.opacity)}
            @input=${(e: Event) => set({ opacity: Number((e.target as HTMLInputElement).value) })}
          />
          <span class="value">${Math.round(style.opacity * 100)}%</span>
        </span>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-item': SgsLayerItem;
  }
}
