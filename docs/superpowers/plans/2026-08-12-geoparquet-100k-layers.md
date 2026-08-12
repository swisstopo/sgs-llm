# GeoParquet 100k Chat Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish complete chat-generated vector layers as GeoParquet, render as many as 100,000 features in the browser without tiles, and show actionable MCP failure reasons.

**Architecture:** Geosearch keeps fetched features in its existing per-process result cache, serializes displayed results to GeoParquet 1.1, and publishes them through the existing S3/local artifact seam. The frontend transfers each downloaded Parquet buffer to a dedicated worker, receives GeoJSON feature chunks, and adds those chunks to one ordinary OpenLayers vector source. The backend classifies a top-level MCP `error` result as a failed tool step so the existing progress UI displays the safe reason.

**Tech Stack:** Python 3.12, MCP 2.0, PyArrow 18.1, Shapely 2.1, boto3/S3, FastAPI, TypeScript 5.9, Lit 3, OpenLayers 10, Vite 7 workers, hyparquet 1.28.1, hyparquet-compressors 1.1.1, pytest, Vitest, Playwright CLI, Docker/ECS/CloudFront.

## Global Constraints

- Accept no more than exactly 100,000 features after text filtering and boundary clipping.
- Reject larger results before caching or publication; never truncate them.
- The user-facing rejection is `Result contains more than 100,000 features. Narrow the place, area, or dataset.`
- Geosearch-produced feature layers use GeoParquet 1.1, WKB, OGC CRS84, Zstandard compression, and 64,000-row groups.
- Keep GeoJSON protocol compatibility for mock/older producers; geosearch emits `format: "parquet"`.
- Decode GeoParquet in a dedicated browser worker and render it as an ordinary OpenLayers vector layer.
- Do not add MVT, PMTiles, a tile server, generated tiles, a new load balancer, or a new artifact store.
- Unexpected MCP exceptions expose only a stable tool name and exception class; detailed traces stay in logs.
- Apply tests before production changes and witness every new regression test fail for the intended reason.
- Commit each completed task separately; use immutable commit-SHA image tags for AWS.

---

### Task 1: GeoParquet writer and artifact publisher

**Files:**
- Create: `geosearch/artifacts.py`
- Create: `geosearch/test_artifacts.py`
- Modify: `geosearch/requirements.txt`
- Modify: `geosearch/s3.py`
- Modify: `geosearch/test_geosearch.py`

**Interfaces:**
- Produces: `write_geoparquet(features: list[dict[str, Any]], destination: Path) -> None`.
- Produces: `S3Store.publish_geoparquet(name: str, features: list[dict[str, Any]]) -> str | None`.
- Preserves: `S3Store.get_geojson()` and the image-baked GeoJSON boundary store.

- [ ] **Step 1: Add writer conformance tests before production code**

  Add tests that write real Point, LineString, Polygon, multi-geometry, null-property,
  reserved-name, nested-property, and mixed-type records. Assert the `geo` metadata,
  CRS84, WKB decoding, feature IDs, original property mapping, bbox, Zstandard codec,
  and a 64,001-row file split into row groups of 64,000 and one.

- [ ] **Step 2: Run the writer tests and witness RED**

  Run:

  ```bash
  .venv/bin/python -m pytest geosearch/test_artifacts.py -q
  ```

  Expected: collection fails because `geosearch.artifacts` does not exist.

- [ ] **Step 3: Implement the minimal deterministic writer**

  Pin `pyarrow==18.1.0`. Build Arrow arrays with `feature_id`, `geometry`, and stable
  sorted property columns. Use `shapely.geometry.shape(...).wkb`, deterministic compact
  JSON for mixed/nested values, GeoParquet 1.1 schema metadata, Zstandard, and
  `row_group_size=64_000`. Raise `ValueError` for empty or invalid geometries.

- [ ] **Step 4: Add S3/local publishing tests before publisher code**

  Assert `.parquet` naming, `application/vnd.apache.parquet`, exact uploaded bytes,
  presigned URL behavior, temporary-file cleanup after success/failure, and a `None`
  result plus logged exception on serialization/upload failure.

- [ ] **Step 5: Run publisher tests and witness RED**

  Run the new `publish_geoparquet` tests and expect `AttributeError` because the method
  is absent.

- [ ] **Step 6: Implement asynchronous GeoParquet publishing**

  Write and upload inside `asyncio.to_thread` using a private `TemporaryDirectory`, then
  generate the existing one-hour presigned URL. Do not change boundary seeding or S3
  lifecycle behavior.

- [ ] **Step 7: Verify Task 1 and commit**

  ```bash
  .venv/bin/python -m pytest geosearch/test_artifacts.py geosearch/test_geosearch.py -q
  .venv/bin/ruff check geosearch/artifacts.py geosearch/s3.py geosearch/test_artifacts.py
  .venv/bin/mypy geosearch
  git diff --check
  git add geosearch/artifacts.py geosearch/test_artifacts.py geosearch/requirements.txt geosearch/s3.py geosearch/test_geosearch.py
  git commit -m "feat(geosearch): publish chat layers as GeoParquet"
  ```

### Task 2: Exact 100,000-feature boundary

**Files:**
- Modify: `geosearch/server.py`
- Modify: `geosearch/test_server.py` or the existing server contract test module
- Modify: `geosearch/README.md`

**Interfaces:**
- Produces: `MAX_LAYER_FEATURES = 100_000`.
- Changes: `filter_features` returns `{"error": <message>, "feature_count": N, "limit": 100000}` when `N > 100_000`.
- Changes: `display_layer` and `display_division` call `publish_geoparquet` and emit `.parquet`/`format: "parquet"`.

- [ ] **Step 1: Add exact-boundary and publication tests before server changes**

  Cover 100,000 accepted, 100,001 rejected, limit checked after `contains`, limit checked
  after boundary clipping, rejected results absent from `ResultCache`, `display_layer`
  emitting Parquet, division publication emitting Parquet, and publication failure
  returning a semantic `error` object.

- [ ] **Step 2: Run focused tests and witness RED**

  ```bash
  .venv/bin/python -m pytest geosearch/test_server.py -q
  ```

  Expected: failures show no cap and calls to `publish_geojson`.

- [ ] **Step 3: Implement the cap and switch geosearch output**

  Apply `contains` and `clip`, then reject `len(features) > MAX_LAYER_FEATURES` before
  `cache.put`. Keep `compute` exact. Publish the retained features directly with
  `publish_geoparquet`; keep the baked boundary source files as GeoJSON and convert only
  when publishing them to the browser.

- [ ] **Step 4: Verify Task 2 and commit**

  ```bash
  .venv/bin/python -m pytest geosearch -q
  .venv/bin/ruff check geosearch
  .venv/bin/mypy geosearch
  git diff --check
  git add geosearch/server.py geosearch/test_server.py geosearch/README.md
  git commit -m "feat(geosearch): cap complete feature layers at 100k"
  ```

### Task 3: Semantic MCP errors in chat progress

**Files:**
- Modify: `backend/app/mcp/client.py`
- Modify: `backend/tests/test_mcp.py`
- Modify: `backend/app/agent/loop.py`
- Modify: `backend/tests/test_loop.py`

**Interfaces:**
- Produces: a private helper that extracts only a non-empty top-level string `error` from parsed tool data.
- Changes: `ToolSession.call()` returns `ToolOutcome(..., is_error=True)` for that shape even when MCP transport reports success.
- Preserves: transport exception text as `Tool <name> failed: <ExceptionClass>` with the full traceback logged only server-side.

- [ ] **Step 1: Add semantic-error and redaction tests before production code**

  Assert a result with `{"error": "Result contains more than 100,000..."}` becomes an
  error outcome; nested/property fields named `error` do not; empty/non-string error
  values do not; the progress event has `status="failed"` and exact safe detail; model
  toolResult status is `error`; transport errors expose no exception message, URL,
  arguments, or cause-chain secrets.

- [ ] **Step 2: Run focused backend tests and witness RED**

  ```bash
  cd backend
  ../.venv/bin/python -m pytest tests/test_mcp.py tests/test_loop.py -q
  ```

- [ ] **Step 3: Implement semantic classification without changing the wire schema**

  Parse the MCP result exactly once, classify only the top-level string, and reuse the
  existing `Intermediate.detail` field. Keep the safe detail capped at the existing 400
  characters.

- [ ] **Step 4: Verify Task 3 and commit**

  ```bash
  cd backend
  ../.venv/bin/python -m pytest tests/test_mcp.py tests/test_loop.py -q
  ../.venv/bin/ruff check app/mcp/client.py app/agent/loop.py tests/test_mcp.py tests/test_loop.py
  ../.venv/bin/mypy app
  cd ..
  git diff --check
  git add backend/app/mcp/client.py backend/app/agent/loop.py backend/tests/test_mcp.py backend/tests/test_loop.py
  git commit -m "fix(backend): surface semantic MCP tool errors"
  ```

### Task 4: Browser GeoParquet worker and OpenLayers integration

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/map/geoparquet.ts`
- Create: `frontend/src/map/geoparquet.test.ts`
- Create: `frontend/src/map/geoparquet.worker.ts`
- Create: `frontend/src/map/geoparquetWorkerClient.ts`
- Create: `frontend/src/map/geoparquetWorkerClient.test.ts`
- Modify: `frontend/src/services/LayerService.ts`
- Modify: `frontend/src/services/LayerService.test.ts`
- Modify: `frontend/src/components/chat/sgs-layer-result-card.ts`
- Modify: `frontend/src/components/chat/sgs-layer-result-card.test.ts`

**Interfaces:**
- Produces: `decodeGeoParquet(buffer: ArrayBuffer) -> Promise<DecodedFeature[]>`.
- Produces: worker messages `{type: "chunk", features}`, `{type: "done"}`, and `{type: "error", message}`.
- Produces: `loadGeoParquet(url, onChunk, signal?) -> Promise<void>` whose worker and fetch are cancelled together.
- Changes: `LayerService.addDataLayer()` accepts both `geojson` and `parquet`.

- [ ] **Step 1: Install exact decoder dependencies**

  ```bash
  cd frontend
  npm install --save-exact hyparquet@1.28.1 hyparquet-compressors@1.1.1
  ```

- [ ] **Step 2: Add real-file decoder tests before decoder code**

  Use a small committed GeoParquet fixture produced by Task 1. Assert IDs, original
  reserved property names, booleans/numbers/strings/nulls, all supported geometry
  families, and rejection of missing GeoParquet metadata, non-WKB geometry, or non-CRS84
  metadata.

- [ ] **Step 3: Run decoder tests and witness RED**

  ```bash
  npm test -- src/map/geoparquet.test.ts
  ```

  Expected: module import fails because `geoparquet.ts` does not exist.

- [ ] **Step 4: Implement pure decoding and worker chunking**

  Use `parquetMetadataAsync` for validation and `parquetReadObjects` with the pinned
  `compressors`. Restore mapped property names, set GeoJSON `id`, and strip internal
  columns. The worker posts at most 2,000 features per chunk and transfers no second copy
  of the input buffer.

- [ ] **Step 5: Add worker-client lifecycle tests before client code**

  Assert successful chunk order, worker error rejection, HTTP status failure, abort
  terminating the worker, late messages ignored, and worker termination after `done`.

- [ ] **Step 6: Run worker-client tests and witness RED, then implement the client**

  ```bash
  npm test -- src/map/geoparquetWorkerClient.test.ts
  ```

  Fetch with `AbortSignal`, transfer the resulting buffer to a Vite module worker, and
  guarantee one resolve/reject plus termination in every exit path.

- [ ] **Step 7: Add LayerService/card tests before integration code**

  Assert `parquet` is offered as supported, chunks become EPSG:2056 OpenLayers features,
  the layer is inserted only after `done`, failures insert no partial layer, duplicate
  loads are suppressed, removal/clear aborts pending work, styling/popup properties are
  preserved, and GeoJSON compatibility remains green.

- [ ] **Step 8: Run integration tests and witness RED, then connect the worker**

  ```bash
  npm test -- src/services/LayerService.test.ts src/components/chat/sgs-layer-result-card.test.ts
  ```

  Build one pending-load controller per layer ID. Convert worker chunks through
  OpenLayers `GeoJSON.readFeatures` with data projection EPSG:4326 and feature projection
  EPSG:2056. Add bounded chunks to a private source; insert the layer only when complete.

- [ ] **Step 9: Verify Task 4 and commit**

  ```bash
  npm test
  npm run typecheck
  npm run lint
  npm run format:check
  npm run build
  cd ..
  git diff --check
  git add frontend/package.json frontend/package-lock.json frontend/src/map frontend/src/services/LayerService.ts frontend/src/services/LayerService.test.ts frontend/src/components/chat/sgs-layer-result-card.ts frontend/src/components/chat/sgs-layer-result-card.test.ts
  git commit -m "feat(frontend): render GeoParquet chat layers"
  ```

### Task 5: Cross-layer documentation and 100,000-feature proof

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/protocol.md`
- Modify: `docs/protocol/server-events.schema.json` only if its existing `parquet` enum or description is incomplete
- Modify: `docs/deployment.md`
- Modify: `geosearch/README.md`
- Modify: `.github/workflows/geosearch.yml`
- Add a focused smoke helper only if the existing test runners cannot express the real cross-language check

**Interfaces:**
- Documents the GeoParquet artifact and exact 100,000 boundary.
- CI geosearch image smoke imports PyArrow and validates a real GeoParquet artifact in addition to `/health` and MCP Host-header checks.

- [ ] **Step 1: Add the production-image smoke assertion before workflow changes**

  Extend the existing image smoke command so the built `linux/amd64` container writes a
  small GeoParquet file and a validator reads its metadata/row count. Run the equivalent
  command locally and witness failure against the pre-change image if available.

- [ ] **Step 2: Document the implemented path**

  Replace GeoJSON-only statements for chat-produced layers with GeoParquet, retain
  official GeoJSON catalogue behavior, state the exact fail-closed cap, browser worker
  decoding, existing 30-day S3 lifecycle, one-hour presigned URL, and absence of tiles.

- [ ] **Step 3: Run a real 100,000-feature cross-language smoke**

  Generate 100,000 deterministic point features with Task 1, validate the output with
  PyArrow/Shapely, decode the same bytes with the production frontend decoder, assert
  exactly 100,000 IDs and geometries, and record elapsed time and artifact size. Run the
  100,001 server boundary test separately and assert no publish call.

- [ ] **Step 4: Run full local verification and commit**

  ```bash
  .venv/bin/python -m pytest geosearch -q
  cd backend && ../.venv/bin/python -m pytest -q && cd ..
  cd frontend && npm test && npm run typecheck && npm run lint && npm run format:check && npm run build && cd ..
  .venv/bin/ruff check geosearch backend/app backend/tests
  .venv/bin/mypy geosearch backend/app
  git diff --check
  git status --short
  git add .github/workflows/geosearch.yml docs/architecture.md docs/protocol.md docs/protocol/server-events.schema.json docs/deployment.md geosearch/README.md
  git commit -m "test: verify 100k GeoParquet layers end to end"
  ```

### Task 6: Local browser acceptance

**Files:**
- No committed files expected.
- Store screenshots/traces, if needed, under ignored `output/playwright/`.

**Interfaces:**
- Exercises the production frontend bundle against local backend/geosearch services.

- [ ] **Step 1: Start local services with the existing documented commands**

  Run geosearch with its local moto artifact store, backend with the local MCP URL, and
  Vite. Confirm `/health` for both services and a clean browser console before the test.

- [ ] **Step 2: Exercise a normal real chat layer**

  Ask for a place-scoped vector layer, add it to the map, inspect feature attributes,
  change symbology, and verify the network response is `.parquet` with Parquet media type.

- [ ] **Step 3: Exercise the deterministic 100,000 fixture and controlled over-limit path**

  Load the generated 100,000-feature artifact through the same LayerService path, pan and
  click while loading, verify all features arrive and the UI remains responsive. Invoke
  the controlled 100,001 server fixture and verify the progress step displays the exact
  actionable failure rather than an unsupported layer or partial map.

### Task 7: Review, immutable images, AWS rollout, and live verification

**Files:**
- No new source files expected; deployment scripts register immutable ECS revisions.

**Interfaces:**
- Backend image: `259789526488.dkr.ecr.eu-central-1.amazonaws.com/sgs-llm-backend:<commit-sha>`.
- Geosearch image: `259789526488.dkr.ecr.eu-central-1.amazonaws.com/sgs-llm-geosearch:<commit-sha>`.
- Frontend: `s3://sgs-llm-frontend-259789526488` behind CloudFront distribution `E2AEIO5QX64WCY`.

- [ ] **Step 1: Perform final diff and history review**

  Compare `origin/main...HEAD`; confirm every changed file serves the approved spec, no
  MVT/tile code exists, no credentials/account artifacts entered the diff, dependencies
  are exact, and the worktree/index are clean. Resolve every Critical/Important review
  finding and rerun affected tests.

- [ ] **Step 2: Confirm rollback state and AWS identity before mutation**

  Record the current backend/geosearch task definition ARNs, image tags, service health,
  frontend S3 version state, CloudFront ETag/status, and `aws sts get-caller-identity` for
  profile `swisstopo`. Stop if the account is not `259789526488` or region is not
  `eu-central-1`.

- [ ] **Step 3: Build and deploy immutable backend/geosearch images**

  From the repository root after all commits:

  ```bash
  PROFILE=swisstopo ./scripts/deploy-backend.sh
  PROFILE=swisstopo ./scripts/deploy-geosearch.sh
  ```

  Both scripts must build for the task's `linux/amd64` runtime, push the exact commit
  tag, register a new task definition, wait for ECS stability, and leave the previous
  task definition available for rollback.

- [ ] **Step 4: Deploy the production frontend**

  ```bash
  PROFILE=swisstopo ./scripts/deploy-frontend.sh
  ```

  Wait for the CloudFront invalidation and distribution deployment, then verify the
  HTML references the new fingerprinted bundle and no old Vite dependency cache is used.

- [ ] **Step 5: Verify AWS health, logs, and live behavior**

  Confirm both ECS services are stable and healthy on the new commit image. Inspect
  CloudWatch logs for startup, PyArrow/import errors, MCP 421/5xx, upload errors, and
  unexpected exceptions. Through `https://denpw8uo5zpkl.cloudfront.net/`, ask for a
  real vector layer, add it, confirm a successful Parquet fetch/decode/map/popup path,
  and confirm the browser console has no errors.

- [ ] **Step 6: Verify the user-facing failure contract**

  Exercise only the safe controlled over-limit fixture or unit/integration seam; do not
  issue a costly unbounded production query merely to force 100,001 live features. Verify
  the same backend/frontend production build displays the exact failed-step detail.

- [ ] **Step 7: Final handoff**

  Report commit SHAs, exact test counts, image tags, task definition revisions, live URL,
  normal-layer evidence, controlled limit evidence, retained rollback revisions, and any
  unverified production acceptance separately. Do not claim completion without fresh
  command and browser evidence.
