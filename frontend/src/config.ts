/**
 * Runtime configuration and service base URLs.
 *
 * All external endpoints are defined here so a deployment can swap them for a
 * proxy in one place (the public Swisstopo APIs allow cross-origin requests
 * today, but that is operational behavior, not a contract).
 */

export interface RuntimeConfig {
  /** WebSocket endpoint of the agent backend (protocol v1). */
  agentWsUrl: string;
}

const DEFAULT_CONFIG: RuntimeConfig = {
  agentWsUrl: 'ws://localhost:8787/ws/v1',
};

/** Swisstopo REST services (search, identify, legends, layer metadata). */
export const API3_BASE_URL = 'https://api3.geo.admin.ch/rest/services';

/** Swisstopo WMTS tile service. */
export const WMTS_BASE_URL = 'https://wmts.geo.admin.ch/1.0.0';

let runtimeConfig: RuntimeConfig = DEFAULT_CONFIG;

export function mergeConfig(raw: unknown): RuntimeConfig {
  if (typeof raw !== 'object' || raw === null) {
    return { ...DEFAULT_CONFIG };
  }
  const candidate = raw as Partial<RuntimeConfig>;
  return {
    agentWsUrl:
      typeof candidate.agentWsUrl === 'string' && candidate.agentWsUrl.length > 0
        ? candidate.agentWsUrl
        : DEFAULT_CONFIG.agentWsUrl,
  };
}

/**
 * Loads /config.json (deploy-time overridable, served next to the static
 * build). Falls back to defaults when missing or malformed.
 */
export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  try {
    const response = await fetch('/config.json');
    if (!response.ok) {
      runtimeConfig = { ...DEFAULT_CONFIG };
      return runtimeConfig;
    }
    runtimeConfig = mergeConfig(await response.json());
  } catch {
    runtimeConfig = { ...DEFAULT_CONFIG };
  }
  return runtimeConfig;
}

export function getRuntimeConfig(): RuntimeConfig {
  return runtimeConfig;
}
