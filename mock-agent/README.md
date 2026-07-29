# Mock agent

A small Node WebSocket server that stands in for the LLM agent backend during
development. It implements the agent protocol v1 ([`../docs/protocol.md`](../docs/protocol.md))
so the frontend chat works end-to-end before the real backend exists.

```bash
npm install
npm start            # ws://localhost:8787/ws/v1  +  POST http://localhost:8787/feedback
```

## What it does

- **Chat** — on each `user_message` it keyword-routes to a scenario
  (`scenarios/`: flood, solar, parquet, default), streams a few `intermediate`
  tool-progress events, then a `final` markdown answer with a sample data
  layer, then `done`. Scenario text is localized to the request language.
- **Data layers** — bundled GeoJSON in `data/` is served over HTTP with
  permissive CORS, mirroring how the real agent will hand out presigned URLs.
  The `parquet` scenario intentionally returns an unsupported format to
  exercise the client's graceful degradation.
- **Feedback** — `POST /feedback` validates `{category, message, ...}` and
  appends it to `feedback.log` (JSONL, git-ignored; override the path with
  `FEEDBACK_LOG`).
- **Health** — `GET /health` returns `{"status":"ok"}`. This is what the
  production load balancer probes, so the endpoint is part of the backend
  contract, not a mock-only convenience.

## Running as the deployed backend image

`Dockerfile` builds this server as the container the ECS Fargate service runs.
Until the real agent lands under `backend/`, it is the deployed backend — which
means the whole CloudFront → ALB → Fargate path (including the WebSocket upgrade)
is exercised by the reference implementation of the protocol.

```bash
docker build -f mock-agent/Dockerfile -t sgs-llm-backend .   # from the repo root
docker run --rm -p 8787:8787 sgs-llm-backend
```

It shuts down on `SIGTERM` so ECS task draining is clean. See
[`../docs/deployment.md`](../docs/deployment.md#backend-deployment).

## QA triggers (in the chat message text)

- `/error` — plays the error path (`error` + `done`)
- `/slow` — stretches all delays ~4× (to test progress UI and cancel)
- sending a `cancel` event stops the running scenario

The only dependency is `ws`.
