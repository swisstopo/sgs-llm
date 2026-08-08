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
import type { FeatureHit } from '../../services/MapService';
import { featureLabel } from '../../map/featureInfo';
import { popupPlacement } from '../../map/popupPlacement';
import { currentLanguage, t } from '../../i18n/i18n';
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
  private popupResize?: ResizeObserver;
  private identifyCounter = 0;
  private identifyAbort?: AbortController;

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
    const popup = this.querySelector('sgs-identify-popup');
    if (popup) {
      // The popup's height changes as it loads, fills and expands, and each of those can
      // push it off the canvas. Re-place it whenever its size settles rather than
      // guessing the final height at open time, when the content is not rendered yet.
      this.popupResize = new ResizeObserver(() => this.placePopup());
      this.popupResize.observe(popup);
    }
    this.clickSubscription = this.mapService.click$.subscribe((coordinate) => {
      void this.onMapClick(coordinate);
    });
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.clickSubscription?.unsubscribe();
    this.popupResize?.disconnect();
    this.mapService.detach();
  }

  /**
   * Re-pins the popup so it stays on the canvas: above the click when it fits, below
   * when the top edge would clip it, cornered inward near the left and right edges.
   */
  private placePopup(): void {
    const anchor = this.querySelector<HTMLElement>('.sgs-identify-anchor');
    const size = this.mapService.map.getSize();
    if (!this.overlay || !anchor || !this.identifyCoordinate || !size) {
      return;
    }
    const pixel = this.mapService.map.getPixelFromCoordinate(this.identifyCoordinate);
    const rect = anchor.getBoundingClientRect();
    const { positioning, offset } = popupPlacement(
      [pixel[0]!, pixel[1]!],
      [size[0]!, size[1]!],
      [rect.width, rect.height],
    );
    this.overlay.setPositioning(positioning);
    this.overlay.setOffset(offset);
    // ol/Overlay measures the element only when one of its properties actually changes,
    // and on the first call the popup is still empty - so it would keep the placement it
    // computed at zero size. Re-setting the position by value forces one more measure now
    // that the content has rendered. A fresh array is required: ol compares by identity.
    this.overlay.setPosition([...this.identifyCoordinate]);
  }

  /** The layer panel's name for the layer a hit came from, when we know it. */
  private layerLabel(hit: FeatureHit): string | undefined {
    for (const layer of this.layerService.layers) {
      if (this.layerService.olLayerFor(layer.id) === hit.layer) {
        return layer.label;
      }
    }
    return undefined;
  }

  private async onMapClick(coordinate: [number, number]): Promise<void> {
    // Vector features are already in the browser, so answer from them directly. This is
    // the only path that works for the agent's own data layers: their features exist in
    // an S3 GeoJSON file, not in swisstopo's MapServer, so identify would never see them.
    const hit = this.mapService.featureAtPixel(
      this.mapService.map.getPixelFromCoordinate(coordinate),
    );
    if (hit) {
      this.showVectorFeature(hit, coordinate);
      return;
    }

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
    this.identifyAbort?.abort();
    const controller = new AbortController();
    this.identifyAbort = controller;
    this.identifyCoordinate = coordinate;
    this.identifyFeatures = [];
    this.identifyLoading = true;
    this.overlay?.setPosition(coordinate);
    this.placePopup();
    try {
      const features = await identify({
        coordinate,
        layerIds,
        mapExtent: context.mapExtent,
        size: context.size,
        lang: currentLanguage(),
        signal: controller.signal,
      });
      if (requestId !== this.identifyCounter) {
        return;
      }
      this.identifyFeatures = features;
      this.mapService.setHighlight(features.map((feature) => feature.geometry));
    } catch (error) {
      if (!controller.signal.aborted) {
        console.error('identify failed', error);
      }
      if (requestId === this.identifyCounter) {
        this.identifyFeatures = [];
      }
    } finally {
      if (requestId === this.identifyCounter) {
        this.identifyLoading = false;
      }
    }
  }

  /** Opens the popup on a feature we already hold, with no network request. */
  private showVectorFeature(hit: FeatureHit, coordinate: [number, number]): void {
    // Supersede any identify still in flight, so its late result cannot replace this.
    this.identifyCounter += 1;
    this.identifyAbort?.abort();
    const properties = hit.feature.getProperties();
    delete properties.geometry;
    const layerName = this.layerLabel(hit) ?? '';
    this.identifyCoordinate = coordinate;
    this.identifyLoading = false;
    this.identifyFeatures = [
      {
        layerBodId: 'vector',
        layerName,
        featureId: String(hit.feature.getId() ?? 0),
        label: featureLabel(properties, t('identify.feature')),
        properties,
      },
    ];
    this.overlay?.setPosition(coordinate);
    this.placePopup();
    this.mapService.highlightFeature(hit.feature);
  }

  private closeIdentify = (): void => {
    this.identifyCounter += 1;
    this.identifyAbort?.abort();
    this.overlay?.setPosition(undefined);
    // Also the flag placePopup checks: closing shrinks the popup, and that resize would
    // otherwise call placePopup, which re-sets the position and puts it back on screen.
    this.identifyCoordinate = undefined;
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
