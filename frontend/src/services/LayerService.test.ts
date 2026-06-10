import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ImageLayer from 'ol/layer/Image';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import ImageWMS from 'ol/source/ImageWMS';
import TileWMS from 'ol/source/TileWMS';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { LayerService } from './LayerService';
import type { CatalogService } from './CatalogService';
import type { MapService } from './MapService';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import { registerProjections } from '../lib/projection';

// GeoJSON features are reprojected to the EPSG:2056 map projection.
registerProjections();

function config(id: string, overrides: Partial<LayerConfig>): LayerConfig {
  return {
    id,
    type: 'wmts',
    label: id,
    attribution: 'swisstopo',
    background: false,
    tooltip: false,
    hasLegend: false,
    ...overrides,
  };
}

const CONFIGS = new Map<string, LayerConfig>(
  [
    config('wmts', { format: 'png', timestamps: ['current'] }),
    config('wms-tiled', { type: 'wms', wmsLayers: 'wms-tiled', gutter: 25 }),
    config('wms-single', { type: 'wms', wmsLayers: 'a,b', singleTile: true, opacity: 0.75 }),
    config('geo', {
      type: 'geojson',
      geojsonUrl: 'https://data.example.ch/geo.json',
      updateDelay: 60000,
    }),
    config('agg', { type: 'aggregate' }),
  ].map((entry) => [entry.id, entry]),
);

class FakeMapService {
  readonly map = { addLayer: vi.fn(), removeLayer: vi.fn() };
  readonly fitBBox = vi.fn();
  readonly fitLV95Extent = vi.fn();
}

class FakeCatalogService {
  getLayer(id: string): Promise<LayerConfig | undefined> {
    return Promise.resolve(CONFIGS.get(id));
  }

  getConfig(): Promise<Map<string, LayerConfig>> {
    return Promise.resolve(CONFIGS);
  }
}

const GEOJSON = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [7.44, 46.95] },
      properties: { name: 'Bern' },
    },
  ],
};

describe('LayerService official layers', () => {
  let mapService: FakeMapService;
  let service: LayerService;
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response(JSON.stringify(GEOJSON)));
    mapService = new FakeMapService();
    service = new LayerService(
      mapService as unknown as MapService,
      new FakeCatalogService() as unknown as CatalogService,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function addedLayer(): unknown {
    return mapService.map.addLayer.mock.calls.at(-1)?.[0];
  }

  it('adds tiled WMS layers with gutter', async () => {
    expect(await service.addOfficialLayer('wms-tiled')).toBe('added');
    const layer = addedLayer() as TileLayer;
    expect(layer).toBeInstanceOf(TileLayer);
    const source = layer.getSource() as TileWMS;
    expect(source).toBeInstanceOf(TileWMS);
    expect(source.getParams()).toEqual({ LAYERS: 'wms-tiled', FORMAT: 'image/png' });
    expect(source.getGutter()).toBe(25);
  });

  it('adds single-tile WMS layers as one image with the config opacity', async () => {
    expect(await service.addOfficialLayer('wms-single')).toBe('added');
    const layer = addedLayer() as ImageLayer<ImageWMS>;
    expect(layer).toBeInstanceOf(ImageLayer);
    const source = layer.getSource() as ImageWMS;
    expect(source).toBeInstanceOf(ImageWMS);
    expect(source.getParams()).toEqual({ LAYERS: 'a,b', FORMAT: 'image/png' });
    expect(layer.getOpacity()).toBe(0.75);
  });

  it('keeps WMTS layers on XYZ tiles', async () => {
    expect(await service.addOfficialLayer('wmts')).toBe('added');
    expect((addedLayer() as TileLayer).getSource()).toBeInstanceOf(XYZ);
  });

  it('loads geojson layers and refreshes them until removal', async () => {
    expect(await service.addOfficialLayer('geo')).toBe('added');
    const layer = addedLayer() as VectorLayer;
    expect(layer).toBeInstanceOf(VectorLayer);
    const source = layer.getSource() as VectorSource;
    expect(source.getFeatures()).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(60000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(source.getFeatures()).toHaveLength(1);

    service.removeLayer('geo');
    await vi.advanceTimersByTimeAsync(120000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mapService.map.removeLayer).toHaveBeenCalledWith(layer);
  });

  it('keeps stale geojson features when a refresh fails', async () => {
    await service.addOfficialLayer('geo');
    const source = (addedLayer() as VectorLayer).getSource() as VectorSource;
    fetchMock.mockResolvedValue(new Response('gone', { status: 500 }));
    await vi.advanceTimersByTimeAsync(60000);
    expect(source.getFeatures()).toHaveLength(1);
  });

  it('fails cleanly when the geojson data cannot be loaded', async () => {
    fetchMock.mockResolvedValue(new Response('nope', { status: 404 }));
    expect(await service.addOfficialLayer('geo')).toBe('failed');
    expect(mapService.map.addLayer).not.toHaveBeenCalled();
    expect(service.layers).toHaveLength(0);
  });

  it('reports unsupported and unknown layers', async () => {
    expect(await service.addOfficialLayer('agg')).toBe('unsupported');
    expect(await service.addOfficialLayer('nope')).toBe('unknown');
    expect(mapService.map.addLayer).not.toHaveBeenCalled();
  });

  it('reports duplicates as existing', async () => {
    expect(await service.addOfficialLayer('wmts')).toBe('added');
    expect(await service.addOfficialLayer('wmts')).toBe('exists');
    expect(mapService.map.addLayer).toHaveBeenCalledTimes(1);
  });

  it('moves layers to a target index and recomputes the z-order', async () => {
    await service.addOfficialLayer('wmts');
    await service.addOfficialLayer('wms-tiled');
    await service.addOfficialLayer('wms-single');
    // Newest first: [wms-single, wms-tiled, wmts]
    service.moveLayerToIndex('wmts', 0);
    expect(service.layers.map((layer) => layer.id)).toEqual(['wmts', 'wms-single', 'wms-tiled']);
    const [wmtsLayer, tiledLayer, singleLayer] = mapService.map.addLayer.mock.calls.map(
      (call) => call[0] as TileLayer,
    );
    expect(wmtsLayer!.getZIndex()).toBe(13);
    expect(singleLayer!.getZIndex()).toBe(12);
    expect(tiledLayer!.getZIndex()).toBe(11);
    // Clamped to the last position; unknown ids are ignored.
    service.moveLayerToIndex('wmts', 99);
    expect(service.layers.at(-1)?.id).toBe('wmts');
    const before = service.layers.map((layer) => layer.id);
    service.moveLayerToIndex('nope', 0);
    expect(service.layers.map((layer) => layer.id)).toEqual(before);
  });

  it('zooms only to layers with a finite vector extent', async () => {
    await service.addOfficialLayer('wmts');
    await service.addOfficialLayer('geo');
    expect(service.canZoomTo('wmts')).toBe(false);
    expect(service.canZoomTo('geo')).toBe(true);

    service.zoomToLayer('geo');
    expect(mapService.fitLV95Extent).toHaveBeenCalledTimes(1);
    const extent = mapService.fitLV95Extent.mock.calls[0]![0] as number[];
    expect(extent).toHaveLength(4);
    expect(extent.every(Number.isFinite)).toBe(true);

    service.zoomToLayer('wmts');
    expect(mapService.fitLV95Extent).toHaveBeenCalledTimes(1);
  });

  it('cannot zoom to an empty geojson layer', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ type: 'FeatureCollection', features: [] })),
    );
    await service.addOfficialLayer('geo');
    expect(service.canZoomTo('geo')).toBe(false);
  });

  it('zooms data layers to their WGS84 bbox', async () => {
    expect(
      await service.addDataLayer({
        id: 'chat-1',
        name: 'Result',
        format: 'geojson',
        url: 'https://data.example.ch/chat.json',
        geometry_type: 'point',
        bbox: [7, 46, 8, 47],
      }),
    ).toBe('added');
    mapService.fitBBox.mockClear();
    expect(service.canZoomTo('chat-1')).toBe(true);
    service.zoomToLayer('chat-1');
    expect(mapService.fitBBox).toHaveBeenCalledWith([7, 46, 8, 47]);
  });
});
