import { LitElement, css, html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { layerServiceContext } from '../../context';
import type { LayerService, MapLayerState } from '../../services/LayerService';
import { t } from '../../i18n/i18n';

/** One active layer row: visibility, opacity, reorder, remove. */
@customElement('sgs-layer-item')
export class SgsLayerItem extends LitElement {
  static override styles = css`
    :host {
      display: block;
      padding: 0.5rem 0.25rem;
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
      font-size: 0.875rem;
    }

    .row {
      display: flex;
      align-items: center;
      gap: 0.375rem;
    }

    label.name {
      flex: 1;
      display: flex;
      align-items: center;
      gap: 0.375rem;
      min-width: 0;
      cursor: pointer;
    }

    .label-text {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      margin-top: 0.375rem;
    }

    input[type='range'] {
      flex: 1;
      accent-color: var(--sgc-color-brand, #d8232a);
    }

    button {
      border: none;
      background: none;
      font: inherit;
      cursor: pointer;
      padding: 0.125rem 0.25rem;
      border-radius: 0.25rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
      line-height: 1;
    }

    button:hover:not(:disabled) {
      background: var(--sgc-color-bg--grey, #f0f2f4);
      color: var(--sgc-color-text, #1c2834);
    }

    button:disabled {
      color: var(--sgc-color-text--disabled, #98a6b3);
      cursor: default;
    }
  `;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @property({ attribute: false }) layer!: MapLayerState;
  @property({ type: Boolean }) isFirst = false;
  @property({ type: Boolean }) isLast = false;

  override render() {
    const { layer } = this;
    return html`
      <div class="row">
        <label class="name" title=${layer.label}>
          <input
            type="checkbox"
            .checked=${layer.visible}
            @change=${(e: Event) =>
              this.layerService.setVisible(layer.id, (e.target as HTMLInputElement).checked)}
          />
          <span class="label-text">${layer.label}</span>
        </label>
        ${this.layerService.getZoomBBox(layer.id)
          ? html`
              <button
                title=${t('layers.zoomTo')}
                aria-label=${t('layers.zoomTo')}
                @click=${() => this.layerService.zoomToLayer(layer.id)}
              >
                ⌖
              </button>
            `
          : ''}
        <button
          title=${t('layers.moveUp')}
          aria-label=${t('layers.moveUp')}
          ?disabled=${this.isFirst}
          @click=${() => this.layerService.moveLayer(layer.id, 'up')}
        >
          ▲
        </button>
        <button
          title=${t('layers.moveDown')}
          aria-label=${t('layers.moveDown')}
          ?disabled=${this.isLast}
          @click=${() => this.layerService.moveLayer(layer.id, 'down')}
        >
          ▼
        </button>
        <button
          title=${t('layers.remove')}
          aria-label=${t('layers.remove')}
          @click=${() => this.layerService.removeLayer(layer.id)}
        >
          ✕
        </button>
      </div>
      <div class="controls">
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
