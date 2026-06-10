import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { catalogServiceContext, layerServiceContext, mapServiceContext } from '../../context';
import type { CatalogService } from '../../services/CatalogService';
import type { LayerService } from '../../services/LayerService';
import type { MapService } from '../../services/MapService';
import type { LayerSearchResult, LocationSearchResult } from '../../swisstopo/searchApi';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 300;
const MAX_LOCATIONS = 5;
const MAX_LAYERS = 10;

/** Combined location + layer search against the Swisstopo SearchServer. */
@customElement('sgs-search-panel')
export class SgsSearchPanel extends LitElement {
  static override styles = css`
    :host {
      display: block;
    }

    input {
      width: 100%;
      box-sizing: border-box;
      font: inherit;
      padding: 0.5rem 0.625rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.25rem;
    }

    input:focus {
      outline: 2px solid var(--sgc-color-brand, #d8232a);
      outline-offset: -1px;
    }

    h3 {
      margin: 0.75rem 0 0.25rem;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    li button {
      display: block;
      width: 100%;
      text-align: left;
      border: none;
      background: none;
      font: inherit;
      font-size: 0.875rem;
      padding: 0.375rem 0.5rem;
      border-radius: 0.25rem;
      cursor: pointer;
    }

    li button:hover:not(:disabled) {
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    li button:disabled {
      cursor: default;
      color: var(--sgc-color-text--disabled, #98a6b3);
    }

    .detail {
      display: block;
      font-size: 0.75rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .empty {
      margin: 0.75rem 0 0;
      font-size: 0.875rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }

    .popular {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.375rem;
      margin-top: 0.75rem;
    }

    .popular-label {
      font-size: 0.8125rem;
      color: var(--sgc-color-text--secondary, #4b5a68);
      margin-right: 0.125rem;
    }

    .chip {
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.25rem 0.625rem;
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 999px;
      background: var(--sgc-color-bg--white, #ffffff);
      cursor: pointer;
    }

    .chip:hover {
      border-color: var(--sgc-color-brand, #d8232a);
      color: var(--sgc-color-brand, #d8232a);
    }
  `;

  @consume({ context: catalogServiceContext })
  private catalogService!: CatalogService;

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private locations: LocationSearchResult[] = [];
  @state() private layers: (LayerSearchResult & { displayable: boolean })[] = [];
  @state() private searched = false;

  private debounceHandle?: ReturnType<typeof setTimeout>;
  private requestCounter = 0;
  private abortController?: AbortController;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    // Keep result "added" states fresh when layers change elsewhere.
    new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const hasResults = this.locations.length > 0 || this.layers.length > 0;
    return html`
      <input
        type="search"
        placeholder=${t('search.placeholder')}
        @input=${this.onInput}
        aria-label=${t('search.placeholder')}
      />
      ${!this.searched
        ? html`
            <div class="popular">
              <span class="popular-label">${t('search.popular')}</span>
              ${['search.popularFlood', 'search.popularSolar', 'search.popularForest'].map(
                (key) => html`
                  <button class="chip" @click=${() => this.usePopularSearch(t(key))}>
                    ${t(key)}
                  </button>
                `,
              )}
            </div>
          `
        : nothing}
      ${this.locations.length > 0
        ? html`
            <h3>${t('search.locations')}</h3>
            <ul>
              ${this.locations.map(
                (location) => html`
                  <li>
                    <button @click=${() => this.goToLocation(location)}>
                      ${location.label}
                      ${location.detail !== location.label.toLowerCase()
                        ? html`<span class="detail">${location.detail}</span>`
                        : nothing}
                    </button>
                  </li>
                `,
              )}
            </ul>
          `
        : nothing}
      ${this.layers.length > 0
        ? html`
            <h3>${t('search.layers')}</h3>
            <ul>
              ${this.layers.map(
                (layer) => html`
                  <li>
                    <button
                      ?disabled=${!layer.displayable}
                      title=${!layer.displayable
                        ? t('search.notDisplayable')
                        : this.layerService.isActive(layer.layerId)
                          ? t('geocatalog.remove')
                          : ''}
                      @click=${() => this.toggleLayer(layer.layerId)}
                    >
                      ${layer.label}
                      ${!layer.displayable
                        ? html`<span class="detail">${t('search.notDisplayable')}</span>`
                        : this.layerService.isActive(layer.layerId)
                          ? html`<span class="detail">${t('search.added')}</span>`
                          : nothing}
                    </button>
                  </li>
                `,
              )}
            </ul>
          `
        : nothing}
      ${this.searched && !hasResults
        ? html`<p class="empty">${t('search.noResults')}</p>`
        : nothing}
    `;
  }

  private usePopularSearch(term: string): void {
    const input = this.renderRoot.querySelector('input');
    if (input) {
      input.value = term;
    }
    void this.search(term);
  }

  private onInput(event: Event): void {
    const query = (event.target as HTMLInputElement).value.trim();
    clearTimeout(this.debounceHandle);
    if (query.length < MIN_QUERY_LENGTH) {
      this.locations = [];
      this.layers = [];
      this.searched = false;
      return;
    }
    this.debounceHandle = setTimeout(() => void this.search(query), DEBOUNCE_MS);
  }

  private async search(query: string): Promise<void> {
    const requestId = ++this.requestCounter;
    // Abort the superseded in-flight search instead of just ignoring it.
    this.abortController?.abort();
    const controller = new AbortController();
    this.abortController = controller;
    try {
      // No viewBBox here: the SearchServer bbox FILTERS locations to the box
      // (not just ranking), which would hide places outside the current view
      // — wrong for a geocoder used to fly elsewhere.
      const [locations, layers] = await Promise.all([
        this.catalogService.searchLocations(query, {
          limit: MAX_LOCATIONS,
          signal: controller.signal,
        }),
        this.catalogService.searchLayers(query, currentLanguage(), {
          limit: MAX_LAYERS,
          signal: controller.signal,
        }),
      ]);
      if (requestId !== this.requestCounter) {
        return; // a newer search superseded this one
      }
      this.locations = locations;
      this.layers = layers;
      this.searched = true;
    } catch (error) {
      if (requestId === this.requestCounter && !controller.signal.aborted) {
        console.error('Search failed', error);
        this.locations = [];
        this.layers = [];
        this.searched = true;
      }
    }
  }

  private goToLocation(location: LocationSearchResult): void {
    if (location.bbox) {
      this.mapService.fitBBox(location.bbox);
    } else {
      this.mapService.flyTo([location.lon, location.lat]);
    }
  }

  /** Adds the layer to the map, or removes it if already shown. */
  private async toggleLayer(layerId: string): Promise<void> {
    if (this.layerService.isActive(layerId)) {
      this.layerService.removeLayer(layerId);
    } else {
      await this.layerService.addOfficialLayer(layerId);
    }
    this.requestUpdate();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-search-panel': SgsSearchPanel;
  }
}
