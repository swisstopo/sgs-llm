import { LitElement, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { provide } from '@lit/context';
import { ObservableController } from '../lib/ObservableController';
import { languageChanged$ } from '../i18n/i18n';
import {
  agentClientContext,
  catalogServiceContext,
  chatServiceContext,
  layerServiceContext,
  mapServiceContext,
} from '../context';
import { AgentClient } from '../agent/AgentClient';
import { CatalogService } from '../services/CatalogService';
import { ChatService } from '../services/ChatService';
import { LayerService } from '../services/LayerService';
import { MapService } from '../services/MapService';
import { getRuntimeConfig } from '../config';
import type { AddLayerEventDetail } from './chat/sgs-layer-result-card';
import type { SgsChatPanel } from './chat/sgs-chat-panel';
import './sgs-header';
import './sgs-split-handle';
import './chat/sgs-chat-panel';
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

  // Re-render the whole shell on language change.
  private readonly _language = new ObservableController(this, languageChanged$);

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override render() {
    return html`
      <sgs-header></sgs-header>
      <div class="content" @sgs-add-layer=${this.onAddDataLayer}>
        <sgs-chat-panel></sgs-chat-panel>
        <sgs-split-handle></sgs-split-handle>
        <sgs-map></sgs-map>
      </div>
    `;
  }

  private onAddDataLayer(event: CustomEvent<AddLayerEventDetail>): void {
    // Data-layer rendering lands in the next milestone; acknowledge the card.
    console.info('add data layer requested', event.detail.layer);
    this.querySelector<SgsChatPanel>('sgs-chat-panel')?.markLayerAdded(event.detail.layer.id);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-app': SgsApp;
  }
}
