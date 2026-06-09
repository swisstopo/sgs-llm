import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { mapServiceContext } from '../../context';
import { BASEMAPS } from '../../services/MapService';
import type { BasemapId, MapService } from '../../services/MapService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';

const BASEMAP_LABEL_KEYS: Record<BasemapId, string> = {
  'ch.swisstopo.pixelkarte-grau': 'map.basemapGrey',
  'ch.swisstopo.swissimage': 'map.basemapAerial',
};

@customElement('sgs-basemap-switcher')
export class SgsBasemapSwitcher extends LitElement {
  static override styles = css`
    :host {
      position: absolute;
      bottom: 1.75rem;
      left: 0.75rem;
      z-index: 1;
      display: flex;
      gap: 0.5rem;
    }

    button {
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      background: var(--sgc-color-bg--white, #ffffff);
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.375rem 0.75rem;
      border-radius: 0.25rem;
      cursor: pointer;
      color: var(--sgc-color-text, #1c2834);
      box-shadow: 0 1px 3px rgb(0 0 0 / 0.15);
    }

    button[aria-pressed='true'] {
      border-color: var(--sgc-color-brand, #d8232a);
      color: var(--sgc-color-brand, #d8232a);
      font-weight: 600;
    }
  `;

  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  private basemap?: ObservableController<BasemapId>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.basemap ??= new ObservableController(this, this.mapService.basemap$);
  }

  override render() {
    const active = this.basemap?.value ?? this.mapService.basemap;
    return html`
      ${BASEMAPS.map(
        (id) => html`
          <button aria-pressed=${id === active} @click=${() => this.mapService.setBasemap(id)}>
            ${t(BASEMAP_LABEL_KEYS[id])}
          </button>
        `,
      )}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-basemap-switcher': SgsBasemapSwitcher;
  }
}
