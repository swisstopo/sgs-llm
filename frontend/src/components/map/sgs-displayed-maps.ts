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
import './sgs-layer-item';
import './sgs-legend-dialog';

const BASEMAP_LABEL_KEYS: Record<BasemapId, string> = {
  'ch.swisstopo.pixelkarte-farbe': 'map.basemapColor',
  'ch.swisstopo.pixelkarte-grau': 'map.basemapGrey',
  'ch.swisstopo.swissimage': 'map.basemapAerial',
};

/**
 * "Displayed maps" panel: exclusive background-map card (SwissGeo style,
 * with eye toggles and tile thumbnails) plus the active layers list.
 */
@customElement('sgs-displayed-maps')
export class SgsDisplayedMaps extends LitElement {
  static override styles = css`
    :host {
      display: block;
      padding: 1rem;
      overflow-y: auto;
      min-height: 0;
    }

    .card {
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.5rem;
      padding: 0.875rem;
      background: var(--sgc-color-bg--white, #ffffff);
    }

    .card h3 {
      margin: 0 0 0.625rem;
      font-size: 0.9375rem;
      font-weight: 600;
      padding-bottom: 0.625rem;
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .basemap-row {
      display: flex;
      align-items: center;
      gap: 0.625rem;
      padding: 0.5rem 0.375rem;
      border-radius: 0.375rem;
      font-size: 0.875rem;
    }

    .basemap-row:hover {
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    .basemap-row .name {
      flex: 1;
    }

    .basemap-row[data-inactive] .name {
      color: var(--sgc-color-text--disabled, #98a6b3);
      text-decoration: line-through;
    }

    .eye {
      display: grid;
      place-items: center;
      border: none;
      background: none;
      cursor: pointer;
      padding: 0.25rem;
      border-radius: 0.25rem;
      color: var(--sgc-color-text, #1c2834);
    }

    .basemap-row[data-inactive] .eye {
      color: var(--sgc-color-text--disabled, #98a6b3);
    }

    .eye:hover {
      background: rgb(0 0 0 / 0.06);
    }

    img.thumb {
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 50%;
      object-fit: cover;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .thumb-placeholder {
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 50%;
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    h4 {
      margin: 1.25rem 0 0.375rem;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .empty {
      margin: 0;
      font-size: 0.875rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }
  `;

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
      <div class="card">
        <h3>${t('maps.background')}</h3>
        ${BASEMAPS.map((id) => {
          const isActive = id === active;
          const thumb = thumbnails?.get(id);
          return html`
            <div class="basemap-row" ?data-inactive=${!isActive}>
              <button
                class="eye"
                title=${t(BASEMAP_LABEL_KEYS[id])}
                aria-pressed=${isActive}
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
      </div>
      <h4>${t('maps.activeLayers')}</h4>
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

const eyeOpenIcon = html`
  <svg
    viewBox="0 0 24 24"
    width="20"
    height="20"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"></path>
    <circle cx="12" cy="12" r="3"></circle>
  </svg>
`;

const eyeClosedIcon = html`
  <svg
    viewBox="0 0 24 24"
    width="20"
    height="20"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path
      d="M2.5 12S6 5.5 12 5.5c1.7 0 3.2.5 4.5 1.2M21.5 12S18 18.5 12 18.5c-1.7 0-3.2-.5-4.5-1.2"
    ></path>
    <path d="M4 20L20 4"></path>
  </svg>
`;

declare global {
  interface HTMLElementTagNameMap {
    'sgs-displayed-maps': SgsDisplayedMaps;
  }
}
