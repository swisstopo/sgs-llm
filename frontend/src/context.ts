import { createContext } from '@lit/context';
import type { CatalogService } from './services/CatalogService';
import type { MapService } from './services/MapService';

export const catalogServiceContext = createContext<CatalogService>(Symbol('catalog-service'));
export const mapServiceContext = createContext<MapService>(Symbol('map-service'));
