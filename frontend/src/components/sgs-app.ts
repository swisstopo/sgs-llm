import { LitElement, html, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { keyed } from 'lit/directives/keyed.js';
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
import type { LayerInfoRequest, PanelId } from '../services/UiService';
import { getRuntimeConfig } from '../config';
import { gripIcon, plusIcon } from './shell/icons';
import {
  PANEL_WIDTH_STORAGE_KEY,
  clampPanelWidth,
  panelWidthFromPointer,
} from './shell/panelWidth';
import type { AddLayerEventDetail } from './chat/sgs-layer-result-card';
import type { SgsChatPanel } from './chat/sgs-chat-panel';
import './sgs-header';
import './shell/sgs-nav-rail';
import './shell/sgs-flyout';
import './chat/sgs-chat-panel';
import './chat/sgs-connection-badge';
import './about/sgs-about-panel';
import './catalog/sgs-geocatalog';
import './feedback/sgs-feedback-panel';
import './map/sgs-displayed-maps';
import './map/sgs-layer-info-dialog';
import './map/sgs-locate-button';
import './map/sgs-map';
import './map/sgs-map-legend';
import './map/sgs-zoom-controls';

const PANEL_TITLE_KEYS: Record<PanelId, string> = {
  chat: 'rail.chat',
  maps: 'rail.maps',
  catalog: 'rail.catalog',
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
  private layerInfo?: ObservableController<LayerInfoRequest | null>;

  // Last panel shown; kept while closing so its content stays visible during
  // the slide-out, and so switching cross-fades from the previous panel.
  private _displayedPanel: PanelId | null = null;

  // Re-render the whole shell on language change.
  private readonly _language = new ObservableController(this, languageChanged$);

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this.activePanel ??= new ObservableController(this, this.uiService.activePanel$);
    this.layerInfo ??= new ObservableController(this, this.uiService.layerInfo$);
    this.restorePanelWidth();
  }

  override render() {
    const active = this.activePanel?.value ?? this.uiService.activePanel;
    if (active) {
      this._displayedPanel = active;
    }
    const shown = this._displayedPanel;
    return html`
      <sgs-header></sgs-header>
      <div class="content" @sgs-add-layer=${this.onAddDataLayer}>
        <sgs-nav-rail></sgs-nav-rail>
        <sgs-map></sgs-map>
        <sgs-map-legend></sgs-map-legend>
        <div class="map-controls">
          <sgs-locate-button></sgs-locate-button>
          <sgs-zoom-controls></sgs-zoom-controls>
        </div>
        ${this.renderLayerInfoDialog()}
        <div class="flyout-layer ${active ? 'open' : ''}">
          ${shown
            ? html`
                <sgs-flyout heading=${t(PANEL_TITLE_KEYS[shown])}>
                  ${shown === 'chat'
                    ? html`
                        <sgs-connection-badge slot="header-extra"></sgs-connection-badge>
                        <button
                          class="chat-new"
                          slot="header-extra"
                          title=${t('chat.newConversation')}
                          aria-label=${t('chat.newConversation')}
                          @click=${() => this.chatService.clear()}
                        >
                          ${plusIcon}
                        </button>
                      `
                    : nothing}
                  ${keyed(
                    shown,
                    html`<div class="flyout-content">${this.renderPanel(shown)}</div>`,
                  )}
                </sgs-flyout>
              `
            : nothing}
          <div
            class="flyout-resizer"
            aria-hidden="true"
            @pointerdown=${this.onResizeStart}
            @dblclick=${this.onResizeReset}
          >
            ${gripIcon}
          </div>
        </div>
      </div>
    `;
  }

  private renderLayerInfoDialog() {
    const info = this.layerInfo?.value ?? this.uiService.layerInfo;
    if (!info) {
      return nothing;
    }
    // Keyed per layer so showModal() in firstUpdated re-runs on layer change.
    return keyed(
      info.id,
      html`<sgs-layer-info-dialog
        .layerId=${info.id}
        .layerLabel=${info.label}
        @sgs-close=${() => this.uiService.closeLayerInfo()}
      ></sgs-layer-info-dialog>`,
    );
  }

  private renderPanel(panel: PanelId) {
    switch (panel) {
      case 'chat':
        return html`<sgs-chat-panel></sgs-chat-panel>`;
      case 'maps':
        return html`<sgs-displayed-maps></sgs-displayed-maps>`;
      case 'catalog':
        return html`<sgs-geocatalog></sgs-geocatalog>`;
      case 'feedback':
        return html`<sgs-feedback-panel></sgs-feedback-panel>`;
      case 'about':
        return html`<sgs-about-panel></sgs-about-panel>`;
    }
  }

  /** Restores the persisted flyout width (clamped against the viewport). */
  private restorePanelWidth(): void {
    const stored = Number(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY));
    if (Number.isFinite(stored) && stored > 0) {
      this.style.setProperty(
        '--sgs-flyout-width',
        `${clampPanelWidth(stored, window.innerWidth)}px`,
      );
    }
  }

  /** Drag-to-resize: pointer capture keeps moves on the handle over the map. */
  private onResizeStart(event: PointerEvent): void {
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    handle.setPointerCapture(event.pointerId);
    handle.toggleAttribute('data-dragging', true);
    let width: number | undefined;
    const onMove = (move: PointerEvent) => {
      width = panelWidthFromPointer(move.clientX, window.innerWidth);
      this.style.setProperty('--sgs-flyout-width', `${width}px`);
    };
    const onEnd = () => {
      handle.removeEventListener('pointermove', onMove);
      handle.removeEventListener('pointerup', onEnd);
      handle.removeEventListener('pointercancel', onEnd);
      handle.toggleAttribute('data-dragging', false);
      if (width !== undefined) {
        localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(width));
      }
    };
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onEnd);
    handle.addEventListener('pointercancel', onEnd);
  }

  /** Double-click on the handle restores the default width. */
  private onResizeReset(): void {
    this.style.removeProperty('--sgs-flyout-width');
    localStorage.removeItem(PANEL_WIDTH_STORAGE_KEY);
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
