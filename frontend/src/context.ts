import { createContext } from '@lit/context';
import type { AgentClient } from './agent/AgentClient';
import type { CatalogService } from './services/CatalogService';
import type { ChatService } from './services/ChatService';
import type { LayerService } from './services/LayerService';
import type { MapService } from './services/MapService';
import type { UiService } from './services/UiService';

export const catalogServiceContext = createContext<CatalogService>(Symbol('catalog-service'));
export const mapServiceContext = createContext<MapService>(Symbol('map-service'));
export const layerServiceContext = createContext<LayerService>(Symbol('layer-service'));
export const agentClientContext = createContext<AgentClient>(Symbol('agent-client'));
export const chatServiceContext = createContext<ChatService>(Symbol('chat-service'));
export const uiServiceContext = createContext<UiService>(Symbol('ui-service'));
