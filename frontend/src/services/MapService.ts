import OlMap from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import XYZ from 'ol/source/XYZ';
import { defaults as defaultControls } from 'ol/control/defaults';
import { fromLonLat, transformExtent } from 'ol/proj';
import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { CatalogService } from './CatalogService';
import { isWmtsDisplayable, layerAttribution, wmtsTileUrl } from '../swisstopo/wmts';

export const BASEMAPS = ['ch.swisstopo.pixelkarte-grau', 'ch.swisstopo.swissimage'] as const;
export type BasemapId = (typeof BASEMAPS)[number];

const DEFAULT_BASEMAP: BasemapId = 'ch.swisstopo.pixelkarte-grau';

/** Default view: Switzerland. */
const SWISS_CENTER_LONLAT: [number, number] = [8.2318, 46.8131];
const DEFAULT_ZOOM = 8;

/** [minLon, minLat, maxLon, maxLat] in WGS84. */
export type BBox = [number, number, number, number];

/**
 * Owns the single OpenLayers map instance: view, basemaps, and camera
 * movements. Components attach it to the DOM and react to its subjects.
 */
export class MapService {
  readonly map: OlMap;

  private readonly basemapSubject = new BehaviorSubject<BasemapId>(DEFAULT_BASEMAP);
  private readonly basemapLayers = new Map<BasemapId, TileLayer<XYZ>>();

  constructor(private readonly catalog: CatalogService) {
    this.map = new OlMap({
      controls: defaultControls({ attributionOptions: { collapsible: false } }),
      view: new View({
        center: fromLonLat(SWISS_CENTER_LONLAT),
        zoom: DEFAULT_ZOOM,
        maxZoom: 18,
      }),
    });
    void this.initBasemaps();
  }

  get basemap$(): Observable<BasemapId> {
    return this.basemapSubject.asObservable();
  }

  get basemap(): BasemapId {
    return this.basemapSubject.value;
  }

  attach(target: HTMLElement): void {
    this.map.setTarget(target);
  }

  detach(): void {
    this.map.setTarget(undefined);
  }

  setBasemap(id: BasemapId): void {
    for (const [basemapId, layer] of this.basemapLayers) {
      layer.setVisible(basemapId === id);
    }
    this.basemapSubject.next(id);
  }

  flyTo(lonLat: [number, number], zoom = 12): void {
    this.map.getView().animate({ center: fromLonLat(lonLat), zoom, duration: 400 });
  }

  /** Current viewport as a WGS84 bbox (for the agent's map_context). */
  getViewBBox(): BBox | undefined {
    const size = this.map.getSize();
    if (!size) {
      return undefined;
    }
    const extent = this.map.getView().calculateExtent(size);
    return transformExtent(extent, 'EPSG:3857', 'EPSG:4326') as BBox;
  }

  fitBBox(bbox: BBox): void {
    this.map.getView().fit(transformExtent(bbox, 'EPSG:4326', 'EPSG:3857'), {
      padding: [48, 48, 48, 48],
      maxZoom: 14,
      duration: 400,
    });
  }

  /** Basemap tile parameters come from layersConfig, never hardcoded. */
  private async initBasemaps(): Promise<void> {
    const config = await this.catalog.getConfig();
    for (const id of BASEMAPS) {
      const layerConfig = config.get(id);
      if (!layerConfig || !isWmtsDisplayable(layerConfig)) {
        console.error(`Basemap ${id} is not available as WMTS`);
        continue;
      }
      const layer = new TileLayer({
        source: new XYZ({
          url: wmtsTileUrl(layerConfig),
          attributions: layerAttribution(layerConfig),
          crossOrigin: 'anonymous',
        }),
        zIndex: 0,
        visible: id === this.basemapSubject.value,
      });
      this.basemapLayers.set(id, layer);
      this.map.addLayer(layer);
    }
  }
}
