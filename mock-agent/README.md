# Mock agent

A small Node WebSocket server used as a deterministic UI and protocol test double. It
implements agent protocol v1 ([`../docs/protocol.md`](../docs/protocol.md)) so frontend work
can run end-to-end without Bedrock, AWS credentials, or an MCP server. The production agent
lives in [`../backend/`](../backend/) and connects to the ten-tool
[`../geosearch/`](../geosearch/) MCP server.

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
  permissive CORS, mirroring how the production agent hands out presigned URLs.
  The legacy `parquet` scenario intentionally points to a missing sample asset to exercise
  the client's fetch-error handling; valid GeoParquet produced by `geosearch` is supported.
- **Feedback** — `POST /feedback` validates `{category, message, ...}` and
  appends it to `feedback.log` (JSONL, git-ignored; override the path with
  `FEEDBACK_LOG`).
- **Health** — `GET /health` returns `{"status":"ok"}`. This is what the
  production load balancer probes, so the endpoint is part of the backend
  contract, not a mock-only convenience.

## Running the rollback/reference image

`Dockerfile` builds the historical rollback image for the ECS Fargate service. It remains
useful for checking the CloudFront → ALB → Fargate path, including the WebSocket upgrade,
but the current production image is built from [`../backend/Dockerfile`](../backend/Dockerfile).

```bash
docker build -f mock-agent/Dockerfile -t sgs-llm-backend .   # from the repo root
docker run --rm -p 8787:8787 sgs-llm-backend
```

It shuts down on `SIGTERM` so ECS task draining is clean. See
[`../docs/deployment.md`](../docs/deployment.md#backend-deployment).

The mock agent does not execute MCP tools. It keyword-routes to canned protocol events;
use the real backend plus `geosearch` when testing the tool catalogue or agent planning.

## QA triggers (in the chat message text)

- `/error` — plays the error path (`error` + `done`)
- `/slow` — stretches all delays ~4× (to test progress UI and cancel)
- sending a `cancel` event stops the running scenario

The only dependency is `ws`.
