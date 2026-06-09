import { LitElement, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { provide } from '@lit/context';
import { ObservableController } from '../lib/ObservableController';
import { languageChanged$, t } from '../i18n/i18n';
import { catalogServiceContext, layerServiceContext, mapServiceContext } from '../context';
import { CatalogService } from '../services/CatalogService';
import { LayerService } from '../services/LayerService';
import { MapService } from '../services/MapService';
import './sgs-header';
import './map/sgs-map';

/**
 * Application shell. Renders in light DOM so the OpenLayers subtree under
 * <sgs-map> stays reachable by the document-level `ol/ol.css`; the shell's
 * layout styles live in style/global.css.
 */
@customElement('sgs-app')
export class SgsApp extends LitElement {
  @provide({ context: catalogServiceContext })
  private catalogService = new CatalogService();

  @provide({ context: mapServiceContext })
  private mapService = new MapService(this.catalogService);

  @provide({ context: layerServiceContext })
  private layerService = new LayerService(this.mapService, this.catalogService);

  // Re-render the whole shell on language change.
  private readonly _language = new ObservableController(this, languageChanged$);

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override render() {
    return html`
      <sgs-header></sgs-header>
      <div class="content">
        <aside class="chat-placeholder">
          <p>${t('scaffold.placeholder')}</p>
        </aside>
        <sgs-map></sgs-map>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-app': SgsApp;
  }
}
