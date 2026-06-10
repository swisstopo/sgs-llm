/** Default timeout for Swisstopo API requests. */
const DEFAULT_TIMEOUT_MS = 15_000;

export interface RequestOptions {
  /** Caller-side cancellation (e.g. a superseded search). */
  signal?: AbortSignal;
  timeoutMs?: number;
}

function combineSignals(options: RequestOptions): AbortSignal {
  const timeout = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  return options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
}

async function request(url: string, options: RequestOptions): Promise<Response> {
  const response = await fetch(url, { signal: combineSignals(options) });
  if (!response.ok) {
    throw new Error(`request failed: ${response.status} (${url.split('?')[0]})`);
  }
  return response;
}

/** GET returning parsed JSON, with timeout and optional caller abort. */
export async function fetchJson(url: string, options: RequestOptions = {}): Promise<unknown> {
  return (await request(url, options)).json();
}

/** GET returning text, with timeout and optional caller abort. */
export async function fetchText(url: string, options: RequestOptions = {}): Promise<string> {
  return (await request(url, options)).text();
}
