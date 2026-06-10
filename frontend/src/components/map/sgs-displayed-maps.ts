import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { Task } from '@lit/task';
import { layerServiceContext, mapServiceContext } from '../../context';
import { BASEMAPS } from '../../services/MapService';
import type { BasemapId, MapService } from '../../services/MapService';
import type { LayerService, MapLayerState } from '../../services/LayerService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import { layerRowStyles } from './layerRowStyles';
import { panelBaseStyles } from '../panelStyles';
import { closeIcon, eyeClosedIcon, eyeOpenIcon } from '../shell/icons';
import './sgs-layer-item';

/** Active overlays above this count trigger the performance hint. */
const PERF_HINT_THRESHOLD = 5;

const BASEMAP_LABEL_KEYS: Record<BasemapId, string> = {
  'ch.swisstopo.pixelkarte-farbe': 'map.basemapColor',
  'ch.swisstopo.pixelkarte-grau': 'map.basemapGrey',
  'ch.swisstopo.swissimage': 'map.basemapAerial',
};

/**
 * "Displayed maps" panel: the exclusive background-map card and the active
 * layers card, sharing one row/card style for a coherent look.
 */
@customElement('sgs-displayed-maps')
export class SgsDisplayedMaps extends LitElement {
  static override styles = [
    panelBaseStyles,
    layerRowStyles,
    css`
      img.thumb,
      .thumb-placeholder {
        flex: none;
        width: 2rem;
        height: 2rem;
        border-radius: 50%;
      }

      img.thumb {
        object-fit: cover;
        border: 1px solid var(--sgc-color-border);
      }

      .thumb-placeholder {
        background: var(--sgc-color-bg--grey);
      }

      sgs-layer-item + sgs-layer-item {
        border-top: 1px solid var(--sgc-color-border--subtle);
      }

      /* Insertion indicator while dragging a layer row. */
      sgs-layer-item[data-drop-before] {
        box-shadow: inset 0 2px 0 0 var(--sgc-color-brand);
      }

      sgs-layer-item[data-drop-after] {
        box-shadow: inset 0 -2px 0 0 var(--sgc-color-brand);
      }

      .empty {
        margin: 0;
        padding: 0.75rem 0.875rem;
        font-size: 0.875rem;
        color: var(--sgc-color-text--secondary);
      }

      .perf-hint {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin: 0;
        padding: 0.5rem 0.875rem;
        font-size: 0.75rem;
        color: var(--sgc-color-text--secondary);
        background: var(--sgc-color-bg--grey);
        border-bottom: 1px solid var(--sgc-color-border--subtle);
      }

      .perf-hint span {
        flex: 1;
      }

      .perf-hint button {
        flex: none;
        display: grid;
        place-items: center;
        border: none;
        background: none;
        padding: 0;
        line-height: 0;
        cursor: pointer;
        color: var(--sgc-color-text--secondary);
      }

      .perf-hint button:hover {
        color: var(--sgc-color-text);
      }
    `,
  ];

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  private basemap?: ObservableController<BasemapId>;
  private layers?: ObservableController<MapLayerState[]>;

  @state() private dragId?: string;
  @state() private dropIndex?: number;
  @state() private perfHintDismissed = false;

  private readonly _language = new ObservableController(this, languageChanged$);

  private readonly thumbnailsTask = new Task(this, {
    args: () => [] as const,
    task: async () => {
      const entries = await Promise.all(
        BASEMAPS.map(async (id) => [id, await this.mapService.getBasemapThumbnailUrl(id)] as const),
      );
      return new Map(entries);
    },
  });

  override connectedCallback(): void {
    super.connectedCallback();
    this.basemap ??= new ObservableController(this, this.mapService.basemap$);
    this.layers ??= new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const active = this.basemap?.value ?? this.mapService.basemap;
    const layers = this.layers?.value ?? [];
    const thumbnails = this.thumbnailsTask.value;
    return html`
      <section class="card">
        <h3 class="card-header">${t('maps.background')}</h3>
        ${BASEMAPS.map((id) => {
          const isActive = id === active;
          const thumb = thumbnails?.get(id);
          return html`
            <div class="row" ?data-hidden=${!isActive}>
              <button
                class="icon-btn eye"
                aria-pressed=${isActive}
                title=${t(BASEMAP_LABEL_KEYS[id])}
                aria-label=${t(BASEMAP_LABEL_KEYS[id])}
                @click=${() => this.mapService.setBasemap(id)}
              >
                ${isActive ? eyeOpenIcon : eyeClosedIcon}
              </button>
              <span class="name">${t(BASEMAP_LABEL_KEYS[id])}</span>
              ${thumb
                ? html`<img class="thumb" src=${thumb} alt="" loading="lazy" />`
                : html`<span class="thumb-placeholder"></span>`}
            </div>
          `;
        })}
      </section>

      <section class="card">
        <h3 class="card-header">${t('maps.activeLayers')}</h3>
        ${layers.length > PERF_HINT_THRESHOLD && !this.perfHintDismissed
          ? html`
              <p class="perf-hint">
                <span>${t('layers.performanceHint')}</span>
                <button
                  title=${t('layers.dismissHint')}
                  aria-label=${t('layers.dismissHint')}
                  @click=${() => (this.perfHintDismissed = true)}
                >
                  ${closeIcon}
                </button>
              </p>
            `
          : nothing}
        ${layers.length === 0
          ? html`<p class="empty">${t('layers.empty')}</p>`
          : layers.map(
              (layer, index) => html`
                <sgs-layer-item
                  .layer=${layer}
                  ?isFirst=${index === 0}
                  ?isLast=${index === layers.length - 1}
                  ?data-drop-before=${this.dragId !== undefined && this.dropIndex === index}
                  ?data-drop-after=${this.dragId !== undefined &&
                  index === layers.length - 1 &&
                  this.dropIndex === layers.length}
                  @dragstart=${(e: DragEvent) => this.onDragStart(e, layer.id)}
                  @dragover=${(e: DragEvent) => this.onDragOver(e, index)}
                  @drop=${this.onDrop}
                  @dragend=${this.clearDrag}
                ></sgs-layer-item>
              `,
            )}
      </section>
    `;
  }

  private onDragStart(event: DragEvent, id: string): void {
    // Firefox requires data for the drag to start.
    event.dataTransfer?.setData('text/plain', id);
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
    }
    this.dragId = id;
  }

  private onDragOver(event: DragEvent, index: number): void {
    if (this.dragId === undefined) {
      return;
    }
    event.preventDefault(); // allow dropping
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move';
    }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    this.dropIndex = event.clientY < rect.top + rect.height / 2 ? index : index + 1;
  }

  private onDrop = (event: DragEvent): void => {
    event.preventDefault();
    const layers = this.layers?.value ?? [];
    if (this.dragId !== undefined && this.dropIndex !== undefined) {
      const from = layers.findIndex((layer) => layer.id === this.dragId);
      // Removing the dragged row shifts insertion points below it up by one.
      const to = from >= 0 && from < this.dropIndex ? this.dropIndex - 1 : this.dropIndex;
      this.layerService.moveLayerToIndex(this.dragId, to);
    }
    this.clearDrag();
  };

  private clearDrag = (): void => {
    this.dragId = undefined;
    this.dropIndex = undefined;
  };
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-displayed-maps': SgsDisplayedMaps;
  }
}
