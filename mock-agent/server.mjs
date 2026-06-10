/**
 * Mock agent backend for the SGS LLM prototype.
 *
 * Speaks the WebSocket protocol v1 (docs/protocol.md) on /ws/v1 and serves
 * the bundled sample GeoJSON over HTTP with permissive CORS — mirroring how
 * the real agent will hand out presigned data URLs.
 *
 * QA triggers in the message text: "/error" plays the error path, "/slow"
 * stretches all delays 4x; a `cancel` event stops the running scenario.
 */
import { createServer } from 'node:http';
import { appendFile, readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { routeScenario } from './scenarios/index.mjs';

const PORT = Number(process.env.PORT ?? 8787);
const DATA_DIR = fileURLToPath(new URL('./data', import.meta.url));
const FEEDBACK_LOG = fileURLToPath(new URL('./feedback.log', import.meta.url));
const SUPPORTED_LANGS = new Set(['de', 'fr', 'it', 'en', 'rm']);
const FEEDBACK_CATEGORIES = new Set(['bug', 'feature', 'improvement', 'question', 'other']);
const FEEDBACK_CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'POST, OPTIONS',
  'access-control-allow-headers': 'content-type',
};

const CANCEL_MESSAGES = {
  de: 'Anfrage abgebrochen.',
  fr: 'Requête annulée.',
  it: 'Richiesta annullata.',
  en: 'Request cancelled.',
};

const httpServer = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host}`);
  if (url.pathname === '/feedback') {
    handleFeedback(req, res);
    return;
  }
  if (req.method !== 'GET' || !url.pathname.startsWith('/data/')) {
    res.writeHead(404).end();
    return;
  }
  const fileName = normalize(url.pathname.slice('/data/'.length));
  if (fileName.includes('..') || fileName.includes('/')) {
    res.writeHead(400).end();
    return;
  }
  try {
    const content = await readFile(join(DATA_DIR, fileName));
    res.writeHead(200, {
      'content-type': extname(fileName) === '.geojson' ? 'application/geo+json' : 'application/octet-stream',
      // Mirrors the presigned-URL production behavior: any origin may fetch.
      'access-control-allow-origin': '*',
    });
    res.end(content);
  } catch {
    res.writeHead(404, { 'access-control-allow-origin': '*' }).end();
  }
});

/** Receives feedback form submissions and appends them to a JSONL log. */
function handleFeedback(req, res) {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, FEEDBACK_CORS).end();
    return;
  }
  if (req.method !== 'POST') {
    res.writeHead(405, FEEDBACK_CORS).end();
    return;
  }
  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
    if (body.length > 32_768) {
      req.destroy();
    }
  });
  req.on('end', async () => {
    try {
      const data = JSON.parse(body);
      const valid =
        FEEDBACK_CATEGORIES.has(data.category) &&
        typeof data.message === 'string' &&
        data.message.trim().length > 0;
      if (!valid) {
        res.writeHead(400, FEEDBACK_CORS).end();
        return;
      }
      await appendFile(
        FEEDBACK_LOG,
        JSON.stringify({ ts: new Date().toISOString(), ...data }) + '\n',
      );
      console.log(`[${new Date().toISOString()}] feedback (${data.category}) received`);
      res.writeHead(204, FEEDBACK_CORS).end();
    } catch {
      res.writeHead(400, FEEDBACK_CORS).end();
    }
  });
}

const wss = new WebSocketServer({ server: httpServer, path: '/ws/v1' });

wss.on('connection', (socket, req) => {
  const baseUrl = `http://${req.headers.host ?? `localhost:${PORT}`}`;
  /** message id -> { timers: Timeout[], lang: string } */
  const active = new Map();

  const send = (event) => {
    if (socket.readyState === socket.OPEN) {
      socket.send(JSON.stringify(event));
    }
  };

  const finish = (messageId) => {
    active.delete(messageId);
    send({ type: 'done', message_id: messageId });
  };

  socket.on('message', (raw) => {
    let event;
    try {
      event = JSON.parse(String(raw));
    } catch {
      return;
    }

    if (event?.type === 'cancel' && typeof event.id === 'string') {
      const run = active.get(event.id);
      if (run) {
        run.timers.forEach(clearTimeout);
        send({
          type: 'error',
          message_id: event.id,
          code: 'cancelled',
          message: CANCEL_MESSAGES[run.lang] ?? CANCEL_MESSAGES.de,
        });
        finish(event.id);
      }
      return;
    }

    if (event?.type !== 'user_message' || typeof event.id !== 'string') {
      return;
    }
    const messageId = event.id;
    const content = typeof event.content === 'string' ? event.content : '';
    const lang = SUPPORTED_LANGS.has(event.lang) && event.lang !== 'rm' ? event.lang : 'de';
    const slowFactor = content.includes('/slow') ? 4 : 1;

    console.log(`[${new Date().toISOString()}] ${lang} message: ${content.slice(0, 80)}`);

    const steps = content.includes('/error')
      ? [
          {
            delay: 600,
            event: { type: 'error', code: 'internal', message: 'Simulated internal error (triggered by /error)' },
          },
        ]
      : routeScenario(content, lang, baseUrl);

    const run = { timers: [], lang };
    active.set(messageId, run);
    let elapsed = 0;
    for (const step of steps) {
      elapsed += step.delay * slowFactor;
      run.timers.push(
        setTimeout(() => send({ ...step.event, message_id: messageId }), elapsed),
      );
    }
    run.timers.push(setTimeout(() => finish(messageId), elapsed + 50));
  });

  socket.on('close', () => {
    for (const run of active.values()) {
      run.timers.forEach(clearTimeout);
    }
    active.clear();
  });
});

httpServer.listen(PORT, () => {
  console.log(`mock-agent listening on http://localhost:${PORT} (WS: /ws/v1)`);
});
