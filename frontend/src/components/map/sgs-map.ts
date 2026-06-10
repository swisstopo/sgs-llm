import { LitElement, html } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import Overlay from 'ol/Overlay';
import type { Subscription } from 'rxjs';
import { layerServiceContext, mapServiceContext } from '../../context';
import type { MapService } from '../../services/MapService';
import type { LayerService } from '../../services/LayerService';
import { identify } from '../../swisstopo/identifyApi';
import type { IdentifyFeature } from '../../swisstopo/identifyApi';
import { currentLanguage } from '../../i18n/i18n';
import './sgs-identify-popup';

/**
 * Hosts the OpenLayers map. Renders in light DOM because `ol/ol.css`
 * (controls, attribution, overlays) is a document-level stylesheet that
 * cannot style inside a shadow root.
 */
@customElement('sgs-map')
export class SgsMap extends LitElement {
  @consume({ context: mapServiceContext })
  private mapService!: MapService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  @state() private identifyFeatures: IdentifyFeature[] = [];
  @state() private identifyLoading = false;
  @state() private identifyCoordinate?: [number, number];

  private overlay?: Overlay;
  private clickSubscription?: Subscription;
  private identifyCounter = 0;

  protected override createRenderRoot(): HTMLElement {
    return this;
  }

  override render() {
    return html`
      <div class="sgs-map-target"></div>
      <div class="sgs-identify-anchor">
        <sgs-identify-popup
          .features=${this.identifyFeatures}
          ?loading=${this.identifyLoading}
          .coordinate=${this.identifyCoordinate}
          @sgs-close=${this.closeIdentify}
        ></sgs-identify-popup>
      </div>
    `;
  }

  protected override firstUpdated(): void {
    const target = this.querySelector<HTMLElement>('.sgs-map-target');
    if (target) {
      this.mapService.attach(target);
    }
    const anchor = this.querySelector<HTMLElement>('.sgs-identify-anchor');
    if (anchor) {
      this.overlay = new Overlay({ element: anchor, stopEvent: true });
      this.mapService.map.addOverlay(this.overlay);
    }
    this.clickSubscription = this.mapService.click$.subscribe((coordinate) => {
      void this.onMapClick(coordinate);
    });
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.clickSubscription?.unsubscribe();
    this.mapService.detach();
  }

  private async onMapClick(coordinate: [number, number]): Promise<void> {
    const layerIds = this.layerService.layers
      .filter((layer) => layer.kind === 'official' && layer.visible && layer.config.tooltip)
      .map((layer) => layer.id);
    if (layerIds.length === 0) {
      this.closeIdentify();
      return;
    }
    const context = this.mapService.getIdentifyContext();
    if (!context) {
      return;
    }
    const requestId = ++this.identifyCounter;
    this.identifyCoordinate = coordinate;
    this.identifyFeatures = [];
    this.identifyLoading = true;
    this.overlay?.setPosition(coordinate);
    try {
      const features = await identify({
        coordinate,
        layerIds,
        mapExtent: context.mapExtent,
        size: context.size,
        lang: currentLanguage(),
      });
      if (requestId !== this.identifyCounter) {
        return;
      }
      this.identifyFeatures = features;
      this.mapService.setHighlight(features.map((feature) => feature.geometry));
    } catch (error) {
      console.error('identify failed', error);
      if (requestId === this.identifyCounter) {
        this.identifyFeatures = [];
      }
    } finally {
      if (requestId === this.identifyCounter) {
        this.identifyLoading = false;
      }
    }
  }

  private closeIdentify = (): void => {
    this.identifyCounter += 1;
    this.overlay?.setPosition(undefined);
    this.identifyFeatures = [];
    this.identifyLoading = false;
    this.mapService.clearHighlight();
  };
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-map': SgsMap;
  }
}
