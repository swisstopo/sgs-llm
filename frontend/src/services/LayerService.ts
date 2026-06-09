import TileLayer from 'ol/layer/Tile';
import XYZ from 'ol/source/XYZ';
import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { CatalogService } from './CatalogService';
import type { MapService } from './MapService';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import { isWmtsDisplayable, layerAttribution, wmtsTileUrl } from '../swisstopo/wmts';
import { loadLayerOverrides } from '../layers/loadLayerTree';

export interface OfficialLayerState {
  kind: 'official';
  id: string;
  config: LayerConfig;
  visible: boolean;
  opacity: number;
}

export type AddLayerResult = 'added' | 'exists' | 'unsupported' | 'unknown';

/** Official overlays render above the basemap (zIndex 0). */
const OFFICIAL_BASE_Z_INDEX = 10;

/**
 * Manages the user's active map layers: state for the layer panel and the
 * corresponding OpenLayers layers on the shared map. Array order is display
 * order, first entry on top.
 */
export class LayerService {
  private readonly layersSubject = new BehaviorSubject<OfficialLayerState[]>([]);
  private readonly olLayers = new Map<string, TileLayer<XYZ>>();
  private readonly overrides = loadLayerOverrides();

  constructor(
    private readonly mapService: MapService,
    private readonly catalog: CatalogService,
  ) {}

  get layers$(): Observable<OfficialLayerState[]> {
    return this.layersSubject.asObservable();
  }

  get layers(): OfficialLayerState[] {
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
    this.olLayers.set(id, olLayer);
    this.mapService.map.addLayer(olLayer);
    this.update([
      { kind: 'official', id, config, visible: true, opacity },
      ...this.layersSubject.value,
    ]);
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

  /** Recomputes z-indices from array order (first entry on top) and emits. */
  private update(layers: OfficialLayerState[]): void {
    layers.forEach((layer, index) => {
      this.olLayers.get(layer.id)?.setZIndex(OFFICIAL_BASE_Z_INDEX + (layers.length - index));
    });
    this.layersSubject.next(layers);
  }
}
