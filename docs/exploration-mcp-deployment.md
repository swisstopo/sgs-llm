# Public exploration MCP deployment

The read-only [`exploration-mcp`](../exploration-mcp/README.md) package is mounted into
the existing SGS agent backend. It remains logically independent from the private,
stateful [`geosearch`](../geosearch/README.md) MCP used by the chat, but reuses the
backend's already-running Fargate task, ALB, CloudFront distribution and deploy pipeline.

## Live endpoint

```text
MCP: https://denpw8uo5zpkl.cloudfront.net/mcp
```

This is a stateless Streamable HTTP endpoint for Claude web, Claude Code, Agno, MCP
Inspector, and other remote MCP clients. It is hosted in AWS account `259789526488`,
region `eu-central-1`. The CloudFront URL supplies public HTTPS; the ALB itself accepts
traffic only from CloudFront.

## Architecture

```text
MCP client anywhere
        │ HTTPS POST/GET/DELETE /mcp
        ▼
CloudFront (no cache, forwards MCP headers and viewer address)
        │ HTTP /mcp
        ▼
Existing ALB ──▶ existing 4-vCPU / 8-GB backend Fargate task
                         │
                         ├── FastAPI chat/admin/feedback application
                         └── mounted stateless Swisstopo exploration MCP
                                  ├── packaged catalogue + division snapshots
                                  └── HTTPS reads from api3.geo.admin.ch
```

The MCP has no Bedrock, S3, database, API-key, secret, or private geosearch dependency.
Its search ranking is deterministic and its upstream data is public. Sharing the task
adds no separate Fargate or load-balancer charge. Before the migration, two weeks of live
backend metrics showed average CPU around 0.2%, peak memory around 3.3% of 8 GB, and ample
headroom for this small I/O-bound application.

There is no Lambda cold start. A warm local catalogue lookup returns immediately; tools
that call geo.admin.ch additionally wait for that public API.

## Isolation and public-traffic controls

The MCP shares compute with the chat but not protocol state:

- stateless JSON responses; no MCP session or result handles are retained;
- at most 256 KiB per MCP request;
- 120 MCP requests per viewer address per minute by default;
- at most eight concurrent MCP requests across the task; excess bursts receive `503`;
- exact Host validation derived from `PUBLIC_BASE_URL`;
- browser origins restricted by default to `https://claude.ai` and
  `https://claude.com`; non-browser MCP clients normally send no Origin;
- CORS exposes only the MCP protocol/session headers and supported methods.

The limits are independent from the Bedrock-backed chat's message and WebSocket limits.
They can be changed with `EXPLORATION_MCP_REQUESTS_PER_MINUTE`,
`EXPLORATION_MCP_MAX_CONCURRENT_REQUESTS`, and
`EXPLORATION_MCP_ALLOWED_ORIGINS`.

## Automatic deployment

Every push to `main` that changes `backend/**` or `exploration-mcp/**` runs
[`backend.yml`](../.github/workflows/backend.yml):

1. install both dependency sets;
2. lint, format-check, type-check, and run both test suites;
3. run the standalone MCP stdio smoke test;
4. build the combined backend image;
5. smoke-test backend health, WebSocket upgrade, and MCP initialization;
6. assume the existing scoped backend deploy role through GitHub OIDC;
7. publish an immutable ECR image and roll the existing ECS service;
8. wait for the ECS deployment circuit breaker and service health.

The dedicated [`exploration-mcp.yml`](../.github/workflows/exploration-mcp.yml) remains a
portable-package validation workflow, but it no longer deploys separate compute. Pull
requests validate without deploying. No long-lived AWS key is stored in GitHub.

## One-time CloudFront route

The backend image always serves `/mcp`. The public route is created once by cloning the
existing `/feedback` behavior, which already targets the ALB, disables caching, forwards
viewer headers, and allows all required HTTP methods:

```bash
PROFILE=swisstopo DRY_RUN=1 ./scripts/configure-exploration-mcp-route.sh
PROFILE=swisstopo ./scripts/configure-exploration-mcp-route.sh
```

The script is idempotent and uses the CloudFront ETag so it cannot overwrite a concurrent
configuration update. Remove only this public route without touching the backend:

```bash
PROFILE=swisstopo ACTION=remove ./scripts/configure-exploration-mcp-route.sh
```

## Manual deployment and verification

Build, publish, and roll the shared backend task:

```bash
PROFILE=swisstopo ./scripts/deploy-backend.sh
python exploration-mcp/scripts/smoke_http.py \
  https://denpw8uo5zpkl.cloudfront.net/mcp
```

The deploy script records the previous ECS task definition and prints the exact rollback
command. If the image does not pass the existing `/health` target-group check, the ECS
deployment circuit breaker rolls it back automatically.

## Connect

Claude Code:

```bash
claude mcp add --transport http swisstopo-search \
  https://denpw8uo5zpkl.cloudfront.net/mcp
```

Claude web: open **Settings → Connectors → Add custom connector** and paste the same URL.

Agno:

```python
from agno.tools.mcp import MCPTools

tools = MCPTools(
    transport="streamable-http",
    url="https://denpw8uo5zpkl.cloudfront.net/mcp",
)
```

## Operations and security

- The endpoint is intentionally authless and globally reachable.
- CloudWatch logs are part of the existing `/ecs/sgs-llm-backend` log group.
- A public MCP failure does not change the private `MCP_SERVER_URL` used by the chat.
- A backend image rollback rolls back both APIs because they share one image.
- Add OAuth or edge-level abuse controls before advertising the endpoint for uncontrolled
  high-volume production use.
- The server does not expose geometry, GeoJSON, bulk retrieval, clipping, or the stateful
  `result_id` workflow of the private geosearch service.
