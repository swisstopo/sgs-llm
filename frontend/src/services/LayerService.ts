import GeoJSON from 'ol/format/GeoJSON';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import type BaseLayer from 'ol/layer/Base';
import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { CatalogService } from './CatalogService';
import type { MapService, BBox } from './MapService';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import type { LayerSpec } from '../protocol/v1';
import { isWmtsDisplayable, layerAttribution, wmtsTileUrl } from '../swisstopo/wmts';
import { buildDataLayerStyle } from '../map/dataLayerStyle';
import { loadLayerOverrides } from '../layers/loadLayerTree';

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

  constructor(
    private readonly mapService: MapService,
    private readonly catalog: CatalogService,
  ) {}

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
    if (!isWmtsDisplayable(config)) {
      return 'unsupported';
    }
    const opacity = this.overrides.get(id)?.defaultOpacity ?? config.opacity ?? 1;
    const olLayer = new TileLayer({
      source: new XYZ({
        url: wmtsTileUrl(config),
        attributions: layerAttribution(config),
        crossOrigin: 'anonymous',
      }),
      opacity,
    });
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
      featureProjection: 'EPSG:3857',
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

  /** Bbox a layer can be zoomed to (data layers only). */
  getZoomBBox(id: string): BBox | undefined {
    const layer = this.layers.find((entry) => entry.id === id);
    return layer?.kind === 'data' ? layer.spec.bbox : undefined;
  }

  zoomToLayer(id: string): void {
    const bbox = this.getZoomBBox(id);
    if (bbox) {
      this.mapService.fitBBox(bbox);
    }
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
