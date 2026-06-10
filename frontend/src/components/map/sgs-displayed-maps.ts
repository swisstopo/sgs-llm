import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
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
import { eyeClosedIcon, eyeOpenIcon } from '../shell/icons';
import './sgs-layer-item';
import './sgs-legend-dialog';

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

      .empty {
        margin: 0;
        padding: 0.75rem 0.875rem;
        font-size: 0.875rem;
        color: var(--sgc-color-text--secondary);
      }
    `,
  ];

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  private basemap?: ObservableController<BasemapId>;
  private layers?: ObservableController<MapLayerState[]>;

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
        ${layers.length === 0
          ? html`<p class="empty">${t('layers.empty')}</p>`
          : layers.map(
              (layer, index) => html`
                <sgs-layer-item
                  .layer=${layer}
                  ?isFirst=${index === 0}
                  ?isLast=${index === layers.length - 1}
                ></sgs-layer-item>
              `,
            )}
      </section>

      <sgs-legend-dialog></sgs-legend-dialog>
    `;
  }

  override firstUpdated(): void {
    this.addEventListener('sgs-show-legend', ((
      event: CustomEvent<{ layerId: string; label: string }>,
    ) => {
      void this.renderRoot
        .querySelector('sgs-legend-dialog')
        ?.open(event.detail.layerId, event.detail.label);
    }) as EventListener);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-displayed-maps': SgsDisplayedMaps;
  }
}
