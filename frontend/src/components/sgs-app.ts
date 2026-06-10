import { LitElement, html, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { cache } from 'lit/directives/cache.js';
import { provide } from '@lit/context';
import { ObservableController } from '../lib/ObservableController';
import { languageChanged$, t } from '../i18n/i18n';
import {
  agentClientContext,
  catalogServiceContext,
  chatServiceContext,
  layerServiceContext,
  mapServiceContext,
  uiServiceContext,
} from '../context';
import { AgentClient } from '../agent/AgentClient';
import { CatalogService } from '../services/CatalogService';
import { ChatService } from '../services/ChatService';
import { LayerService } from '../services/LayerService';
import { MapService } from '../services/MapService';
import { UiService } from '../services/UiService';
import type { PanelId } from '../services/UiService';
import { getRuntimeConfig } from '../config';
import type { AddLayerEventDetail } from './chat/sgs-layer-result-card';
import type { SgsChatPanel } from './chat/sgs-chat-panel';
import './sgs-header';
import './shell/sgs-nav-rail';
import './shell/sgs-flyout';
import './chat/sgs-chat-panel';
import './chat/sgs-connection-badge';
import './search/sgs-search-panel';
import './catalog/sgs-geocatalog';
import './map/sgs-displayed-maps';
import './map/sgs-map';

const PANEL_TITLE_KEYS: Record<PanelId, string> = {
  search: 'rail.search',
  maps: 'rail.maps',
  catalog: 'rail.catalog',
  chat: 'rail.chat',
  feedback: 'rail.feedback',
  about: 'rail.about',
};

/**
 * Application shell (SwissGeo-style): header, left icon rail, one flyout
 * panel at a time, map. Renders in light DOM so the OpenLayers subtree under
 * <sgs-map> stays reachable by the document-level `ol/ol.css`; the shell's
 * layout styles live in style/global.css.
 */
@customElement('sgs-app')
export class SgsApp extends LitElement {
  @provide({ context: uiServiceContext })
  private uiService = new UiService();

  @provide({ context: catalogServiceContext })
  private catalogService = new CatalogService();

  @provide({ context: mapServiceContext })
  private mapService = new MapService(this.catalogService);

  @provide({ context: layerServiceContext })
  private layerService = new LayerService(this.mapService, this.catalogService);

  @provide({ context: agentClientContext })
  private agentClient = new AgentClient(() => getRuntimeConfig().agentWsUrl);

  @provide({ context: chatServiceContext })
  private chatService = new ChatService(this.agentClient, () => {
    const bbox = this.mapService.getViewBBox();
    if (!bbox) {
      return undefined;
    }
    return { bbox, active_layer_ids: this.layerService.layers.map((layer) => layer.id) };
  });

  private activePanel?: ObservableController<PanelId | null>;

  // Re-render the whole shell on language change.
  private readonly _language = new ObservableController(this, languageChanged$);

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.activePanel ??= new ObservableController(this, this.uiService.activePanel$);
  }

  override render() {
    const active = this.activePanel?.value ?? this.uiService.activePanel;
    return html`
      <sgs-header></sgs-header>
      <div class="content" @sgs-add-layer=${this.onAddDataLayer}>
        <sgs-nav-rail></sgs-nav-rail>
        ${active
          ? html`
              <sgs-flyout heading=${t(PANEL_TITLE_KEYS[active])} ?wide=${active === 'chat'}>
                ${active === 'chat'
                  ? html`<sgs-connection-badge slot="header-extra"></sgs-connection-badge>`
                  : nothing}
                ${cache(this.renderPanel(active))}
              </sgs-flyout>
            `
          : nothing}
        <sgs-map></sgs-map>
      </div>
    `;
  }

  private renderPanel(panel: PanelId) {
    switch (panel) {
      case 'search':
        return html`<div class="sgs-panel-pad"><sgs-search-panel></sgs-search-panel></div>`;
      case 'chat':
        return html`<sgs-chat-panel></sgs-chat-panel>`;
      case 'maps':
        return html`<sgs-displayed-maps></sgs-displayed-maps>`;
      case 'catalog':
        return html`<sgs-geocatalog></sgs-geocatalog>`;
      case 'feedback':
      case 'about':
        return html`<div class="sgs-panel-pad"></div>`;
    }
  }

  private async onAddDataLayer(event: CustomEvent<AddLayerEventDetail>): Promise<void> {
    const { layer } = event.detail;
    const result = await this.layerService.addDataLayer(layer);
    if (result === 'added' || result === 'exists') {
      this.querySelector<SgsChatPanel>('sgs-chat-panel')?.markLayerAdded(layer.id);
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-app': SgsApp;
  }
}
