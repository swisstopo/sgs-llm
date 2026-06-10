import GeoJSON from 'ol/format/GeoJSON';
import { isEmpty } from 'ol/extent';
import ImageLayer from 'ol/layer/Image';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import ImageWMS from 'ol/source/ImageWMS';
import TileWMS from 'ol/source/TileWMS';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import type BaseLayer from 'ol/layer/Base';
import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { CatalogService } from './CatalogService';
import type { MapService } from './MapService';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import type { LayerSpec } from '../protocol/v1';
import { wmtsTileUrl } from '../swisstopo/wmts';
import { wmsParams, wmsUrl } from '../swisstopo/wms';
import { isDisplayable, layerAttribution } from '../swisstopo/layers';
import { loadGeoAdminStyle } from '../swisstopo/geojsonStyle';
import { fetchJson } from '../swisstopo/http';
import { buildDataLayerStyle } from '../map/dataLayerStyle';
import { lv95TileGrid } from '../map/swissGrid';
import { loadLayerOverrides } from '../layers/layerOverrides';
import { languageChanged$ } from '../i18n/i18n';

interface BaseLayerState {
  id: string;
  label: string;
  visible: boolean;
  opacity: number;
}

/** An official Swisstopo WMTS overlay. */
export interface OfficialLayerState extends BaseLayerState {
  kind: 'official';
  config: LayerConfig;
}

/** A data layer produced by the agent (chat result). */
export interface DataLayerState extends BaseLayerState {
  kind: 'data';
  spec: LayerSpec;
}

export type MapLayerState = OfficialLayerState | DataLayerState;

export type AddLayerResult = 'added' | 'exists' | 'unsupported' | 'unknown' | 'failed';

/** Official overlays and data layers render above the basemap (zIndex 0). */
const OVERLAY_BASE_Z_INDEX = 10;

/**
 * Manages the user's active map layers: state for the layer panel and the
 * corresponding OpenLayers layers on the shared map. Array order is display
 * order, first entry on top.
 */
export class LayerService {
  private readonly layersSubject = new BehaviorSubject<MapLayerState[]>([]);
  private readonly olLayers = new Map<string, BaseLayer>();
  private readonly overrides = loadLayerOverrides();
  /** Periodic re-fetch handles for live geojson layers (rain radar etc.). */
  private readonly refreshTimers = new Map<string, ReturnType<typeof setInterval>>();

  constructor(
    private readonly mapService: MapService,
    private readonly catalog: CatalogService,
  ) {
    // Official layer labels follow the UI language.
    languageChanged$.subscribe(() => void this.refreshLabels());
  }

  private async refreshLabels(): Promise<void> {
    const config = await this.catalog.getConfig();
    this.update(
      this.layersSubject.value.map((layer) => {
        if (layer.kind !== 'official') {
          return layer;
        }
        const updated = config.get(layer.id);
        return updated ? { ...layer, label: updated.label, config: updated } : layer;
      }),
    );
  }

  get layers$(): Observable<MapLayerState[]> {
    return this.layersSubject.asObservable();
  }

  get layers(): MapLayerState[] {
    return this.layersSubject.value;
  }

  isActive(id: string): boolean {
    return this.olLayers.has(id);
  }

  async addOfficialLayer(id: string): Promise<AddLayerResult> {
    if (this.olLayers.has(id)) {
      return 'exists';
    }
    const config = await this.catalog.getLayer(id);
    if (!config) {
      return 'unknown';
    }
    if (!isDisplayable(config)) {
      return 'unsupported';
    }
    const opacity = this.overrides.get(id)?.defaultOpacity ?? config.opacity ?? 1;
    const olLayer =
      config.type === 'wmts'
        ? this.createWmtsLayer(config, opacity)
        : config.type === 'wms'
          ? this.createWmsLayer(config, opacity)
          : await this.createGeoJsonLayer(config, opacity);
    if (!olLayer) {
      return 'failed';
    }
    if (this.olLayers.has(id)) {
      // A concurrent add finished while we awaited config/data.
      return 'exists';
    }
    this.startGeoJsonRefresh(config, olLayer);
    this.insert(olLayer, {
      kind: 'official',
      id,
      label: config.label,
      config,
      visible: true,
      opacity,
    });
    return 'added';
  }

  private createWmtsLayer(config: LayerConfig, opacity: number): BaseLayer {
    return new TileLayer({
      source: new XYZ({
        url: wmtsTileUrl(config),
        projection: 'EPSG:2056',
        tileGrid: lv95TileGrid(),
        attributions: layerAttribution(config),
        crossOrigin: 'anonymous',
      }),
      opacity,
    });
  }

  private createWmsLayer(config: LayerConfig, opacity: number): BaseLayer {
    if (config.singleTile) {
      return new ImageLayer({
        source: new ImageWMS({
          url: wmsUrl(config),
          params: wmsParams(config),
          attributions: layerAttribution(config),
          crossOrigin: 'anonymous',
          ratio: 1,
        }),
        opacity,
      });
    }
    return new TileLayer({
      source: new TileWMS({
        url: wmsUrl(config),
        params: wmsParams(config),
        attributions: layerAttribution(config),
        crossOrigin: 'anonymous',
        gutter: config.gutter ?? 0,
      }),
      opacity,
    });
  }

  /**
   * Official geojson layers are live data: features come from `geojsonUrl`,
   * reprojected from the file's own CRS.
   */
  private async createGeoJsonLayer(
    config: LayerConfig,
    opacity: number,
  ): Promise<BaseLayer | undefined> {
    try {
      const [data, style] = await Promise.all([
        fetchJson(config.geojsonUrl!),
        loadGeoAdminStyle(config.styleUrl),
      ]);
      const source = new VectorSource({
        features: this.readGeoJsonFeatures(data),
        attributions: layerAttribution(config),
      });
      return new VectorLayer({ source, style, opacity });
    } catch (error) {
      console.error(`Failed to load geojson layer ${config.id}`, error);
      return undefined;
    }
  }

  /** Live geojson layers re-fetch every `updateDelay` ms while on the map. */
  private startGeoJsonRefresh(config: LayerConfig, layer: BaseLayer): void {
    if (!(layer instanceof VectorLayer) || !config.updateDelay || config.updateDelay <= 0) {
      return;
    }
    const source = layer.getSource() as VectorSource | null;
    if (!source) {
      return;
    }
    this.refreshTimers.set(
      config.id,
      setInterval(() => void this.refreshGeoJsonSource(config, source), config.updateDelay),
    );
  }

  private readGeoJsonFeatures(data: unknown) {
    // No dataProjection: the format honors the file's `crs` member (EPSG:2056
    // in practice) and defaults to EPSG:4326 when absent.
    return new GeoJSON().readFeatures(data, { featureProjection: 'EPSG:2056' });
  }

  private async refreshGeoJsonSource(config: LayerConfig, source: VectorSource): Promise<void> {
    try {
      const data = await fetchJson(config.geojsonUrl!);
      const features = this.readGeoJsonFeatures(data);
      source.clear(true);
      source.addFeatures(features);
    } catch (error) {
      // Keep the stale features; the next interval retries.
      console.warn(`Failed to refresh geojson layer ${config.id}`, error);
    }
  }

  private clearRefresh(id: string): void {
    const timer = this.refreshTimers.get(id);
    if (timer !== undefined) {
      clearInterval(timer);
      this.refreshTimers.delete(id);
    }
  }

  /** Fetches a chat data layer (GeoJSON) and puts it on the map. */
  async addDataLayer(spec: LayerSpec): Promise<AddLayerResult> {
    if (this.olLayers.has(spec.id)) {
      return 'exists';
    }
    if (spec.format !== 'geojson') {
      return 'unsupported';
    }
    let data: unknown;
    try {
      const response = await fetch(spec.url);
      if (!response.ok) {
        throw new Error(`data layer request failed: ${response.status}`);
      }
      data = await response.json();
    } catch (error) {
      console.error(`Failed to load data layer ${spec.id}`, error);
      return 'failed';
    }
    const features = new GeoJSON().readFeatures(data, {
      dataProjection: 'EPSG:4326',
      featureProjection: 'EPSG:2056',
    });
    const olLayer = new VectorLayer({
      source: new VectorSource({ features }),
      style: buildDataLayerStyle(spec),
      properties: spec.attribution ? { attribution: spec.attribution } : {},
    });
    this.insert(olLayer, {
      kind: 'data',
      id: spec.id,
      label: spec.name,
      spec,
      visible: true,
      opacity: 1,
    });
    if (spec.bbox) {
      this.mapService.fitBBox(spec.bbox);
    }
    return 'added';
  }

  removeLayer(id: string): void {
    const olLayer = this.olLayers.get(id);
    if (!olLayer) {
      return;
    }
    this.clearRefresh(id);
    this.mapService.map.removeLayer(olLayer);
    this.olLayers.delete(id);
    this.update(this.layersSubject.value.filter((layer) => layer.id !== id));
  }

  setVisible(id: string, visible: boolean): void {
    this.olLayers.get(id)?.setVisible(visible);
    this.update(
      this.layersSubject.value.map((layer) => (layer.id === id ? { ...layer, visible } : layer)),
    );
  }

  setOpacity(id: string, opacity: number): void {
    this.olLayers.get(id)?.setOpacity(opacity);
    this.update(
      this.layersSubject.value.map((layer) => (layer.id === id ? { ...layer, opacity } : layer)),
    );
  }

  /** True when the layer has a finite extent the view can zoom to. */
  canZoomTo(id: string): boolean {
    const layer = this.layers.find((entry) => entry.id === id);
    if (layer?.kind === 'data' && layer.spec.bbox) {
      return true;
    }
    return this.getVectorExtent(id) !== undefined;
  }

  zoomToLayer(id: string): void {
    const layer = this.layers.find((entry) => entry.id === id);
    if (layer?.kind === 'data' && layer.spec.bbox) {
      this.mapService.fitBBox(layer.spec.bbox);
      return;
    }
    const extent = this.getVectorExtent(id);
    if (extent) {
      this.mapService.fitLV95Extent(extent);
    }
  }

  /** EPSG:2056 extent of a vector layer's source, undefined when empty/non-vector. */
  private getVectorExtent(id: string): [number, number, number, number] | undefined {
    const olLayer = this.olLayers.get(id);
    if (!(olLayer instanceof VectorLayer)) {
      // WMTS/WMS overlays cover all of Switzerland: nothing useful to zoom to.
      return undefined;
    }
    const extent = (olLayer.getSource() as VectorSource | null)?.getExtent();
    return extent && !isEmpty(extent) ? (extent as [number, number, number, number]) : undefined;
  }

  /** Moves a layer one position up (towards the top) or down. */
  moveLayer(id: string, direction: 'up' | 'down'): void {
    const layers = [...this.layersSubject.value];
    const index = layers.findIndex((layer) => layer.id === id);
    const target = direction === 'up' ? index - 1 : index + 1;
    if (index < 0 || target < 0 || target >= layers.length) {
      return;
    }
    const [moved] = layers.splice(index, 1);
    layers.splice(target, 0, moved!);
    this.update(layers);
  }

  /** Moves a layer to a target position in the display order (0 = top). */
  moveLayerToIndex(id: string, index: number): void {
    const layers = [...this.layersSubject.value];
    const from = layers.findIndex((layer) => layer.id === id);
    if (from < 0) {
      return;
    }
    const to = Math.max(0, Math.min(index, layers.length - 1));
    if (to === from) {
      return;
    }
    const [moved] = layers.splice(from, 1);
    layers.splice(to, 0, moved!);
    this.update(layers);
  }

  private insert(olLayer: BaseLayer, state: MapLayerState): void {
    this.olLayers.set(state.id, olLayer);
    this.mapService.map.addLayer(olLayer);
    this.update([state, ...this.layersSubject.value]);
  }

  /** Recomputes z-indices from array order (first entry on top) and emits. */
  private update(layers: MapLayerState[]): void {
    layers.forEach((layer, index) => {
      this.olLayers.get(layer.id)?.setZIndex(OVERLAY_BASE_Z_INDEX + (layers.length - index));
    });
    this.layersSubject.next(layers);
  }
}
