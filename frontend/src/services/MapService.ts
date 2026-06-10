import OlMap from 'ol/Map';
import View from 'ol/View';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import GeoJSON from 'ol/format/GeoJSON';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import CircleStyle from 'ol/style/Circle';
import Style from 'ol/style/Style';
import { defaults as defaultControls } from 'ol/control/defaults';
import { transformExtent } from 'ol/proj';
import { BehaviorSubject, Subject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { CatalogService } from './CatalogService';
import { isWmtsDisplayable, wmtsTileUrl } from '../swisstopo/wmts';
import { layerAttribution } from '../swisstopo/layers';
import { LV95_EXTENT, LV95_VIEW_RESOLUTIONS, lv95TileGrid } from '../map/swissGrid';

export const BASEMAPS = [
  'ch.swisstopo.pixelkarte-farbe',
  'ch.swisstopo.pixelkarte-grau',
  'ch.swisstopo.swissimage',
] as const;
export type BasemapId = (typeof BASEMAPS)[number];

/** Fixed LV95 tile used for basemap thumbnails (Bern, verified for all basemaps). */
const THUMBNAIL_TILE = { z: 19, x: 35, y: 29 } as const;

const DEFAULT_BASEMAP: BasemapId = 'ch.swisstopo.pixelkarte-grau';

/** Default view: all of Switzerland, centered (LV95). */
const SWISS_CENTER_LV95: [number, number] = [2660000, 1190000];
/** Initial zoom on the LV95 ladder: 500 m/px, the whole country in view. */
const DEFAULT_ZOOM = 1;

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
  private readonly clickSubject = new Subject<[number, number]>();
  private readonly highlightSource = new VectorSource();
  private readonly locationSource = new VectorSource();

  constructor(private readonly catalog: CatalogService) {
    this.map = new OlMap({
      // The zoom buttons are our own (sgs-zoom-controls, bottom-right).
      controls: defaultControls({ zoom: false, attributionOptions: { collapsible: false } }),
      view: new View({
        projection: 'EPSG:2056',
        center: SWISS_CENTER_LV95,
        zoom: DEFAULT_ZOOM,
        // Snap to the official zoom ladder so tiles always render 1:1 (the
        // zoomed-out levels carry the light generalized map style).
        resolutions: LV95_VIEW_RESOLUTIONS,
        constrainResolution: true,
        // Keep the view center on the tile grid, but allow zooming out far
        // enough to see the whole grid (Switzerland + surroundings).
        extent: LV95_EXTENT,
        constrainOnlyCenter: true,
      }),
    });
    this.map.addLayer(
      new VectorLayer({
        source: this.highlightSource,
        zIndex: 1000,
        style: new Style({
          fill: new Fill({ color: 'rgba(255, 200, 0, 0.25)' }),
          stroke: new Stroke({ color: '#ff9000', width: 3 }),
          image: new CircleStyle({
            radius: 9,
            stroke: new Stroke({ color: '#ff9000', width: 3 }),
            fill: new Fill({ color: 'rgba(255, 200, 0, 0.4)' }),
          }),
        }),
      }),
    );
    this.map.addLayer(
      new VectorLayer({
        source: this.locationSource,
        zIndex: 1001,
        style: new Style({
          image: new CircleStyle({
            radius: 8,
            fill: new Fill({ color: '#1c74e9' }),
            stroke: new Stroke({ color: '#ffffff', width: 3 }),
          }),
        }),
      }),
    );
    this.map.on('singleclick', (event) => {
      this.clickSubject.next(event.coordinate as [number, number]);
    });
    void this.initBasemaps();
  }

  /** Places (or moves) the geolocation marker, EPSG:2056. */
  setLocationMarker(coordinate: [number, number]): void {
    this.locationSource.clear();
    this.locationSource.addFeature(new Feature(new Point(coordinate)));
  }

  clearLocationMarker(): void {
    this.locationSource.clear();
  }

  /** Animates the view to a center and resolution (m/px). */
  animateTo(center: [number, number], resolution: number): void {
    this.map.getView().animate({ center, resolution, duration: 600 });
  }

  /** Steps the snapped zoom by the given delta (the view clamps to its ladder). */
  zoomBy(delta: number): void {
    const view = this.map.getView();
    const zoom = view.getZoom();
    if (zoom === undefined) {
      return;
    }
    // Rapid clicks: restart from a constrained target, as ol/control/Zoom does.
    if (view.getAnimating()) {
      view.cancelAnimations();
    }
    view.animate({ zoom: view.getConstrainedZoom(zoom + delta), duration: 250 });
  }

  /** Single clicks on the map, EPSG:2056. */
  get click$(): Observable<[number, number]> {
    return this.clickSubject.asObservable();
  }

  /** Replaces the identify highlight with GeoJSON geometries (EPSG:2056). */
  setHighlight(geometries: unknown[]): void {
    this.highlightSource.clear();
    const format = new GeoJSON();
    for (const geometry of geometries) {
      if (!geometry) {
        continue;
      }
      try {
        this.highlightSource.addFeature(new Feature(format.readGeometry(geometry)));
      } catch {
        // skip unparseable geometries
      }
    }
  }

  clearHighlight(): void {
    this.highlightSource.clear();
  }

  /** Identify context: current extent and viewport size. */
  getIdentifyContext():
    | { mapExtent: [number, number, number, number]; size: [number, number] }
    | undefined {
    const size = this.map.getSize();
    if (!size) {
      return undefined;
    }
    const extent = this.map.getView().calculateExtent(size);
    return {
      mapExtent: extent as [number, number, number, number],
      size: [size[0]!, size[1]!],
    };
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

  /** Thumbnail image URL for a basemap (tile params from layersConfig). */
  async getBasemapThumbnailUrl(id: BasemapId): Promise<string | undefined> {
    const config = (await this.catalog.getConfig()).get(id);
    if (!config || !isWmtsDisplayable(config)) {
      return undefined;
    }
    return wmtsTileUrl(config)
      .replace('{z}', String(THUMBNAIL_TILE.z))
      .replace('{x}', String(THUMBNAIL_TILE.x))
      .replace('{y}', String(THUMBNAIL_TILE.y));
  }

  /** Current viewport as a WGS84 bbox (for the agent's map_context). */
  getViewBBox(): BBox | undefined {
    const size = this.map.getSize();
    if (!size) {
      return undefined;
    }
    const extent = this.map.getView().calculateExtent(size);
    return transformExtent(extent, 'EPSG:2056', 'EPSG:4326') as BBox;
  }

  fitBBox(bbox: BBox): void {
    this.fitLV95Extent(
      transformExtent(bbox, 'EPSG:4326', 'EPSG:2056') as [number, number, number, number],
    );
  }

  /** Fits the view to an EPSG:2056 extent (shared by bbox and layer-extent zooms). */
  fitLV95Extent(extent: [number, number, number, number]): void {
    this.map.getView().fit(extent, {
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
          projection: 'EPSG:2056',
          tileGrid: lv95TileGrid(),
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
