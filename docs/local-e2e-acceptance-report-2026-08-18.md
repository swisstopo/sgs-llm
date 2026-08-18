# Local end-to-end customer acceptance report

**Run date:** 18 August 2026

**Application:** `http://127.0.0.1:5174/`

**Path tested:** browser frontend → WebSocket agent → local MCP → Swisstopo services → chat/map frontend

**Execution:** sequential, one query at a time, using headless Chromium against the real local frontend

## Executive result

| Measure | Result |
|---|---:|
| Customer scenarios | 21 |
| Chat turns | 24 |
| Turns returning a final response | 24 / 24 |
| Protocol errors or failed progress steps | 0 |
| Fully passed acceptance judgments | 22 / 24 turns |
| Partial passes | 2 / 24 turns |
| Total agent time | 423.20 seconds |
| Average turn time | 17.63 seconds |
| Fastest turn | 4.04 seconds |
| Slowest turn | 48.02 seconds |

All ten MCP tools were exercised by the agent during the run:

```text
search_layers
geocode_location
describe_layer
identify_at_point
search_locations
display_division
filter_features
display_catalog_layer
analyze_features
display_layer
```

## Sequential results — individual tool examples

| ID | Query | Tools actually used | Time | Result |
|---|---|---|---:|---|
| T01 | “What official Swiss datasets are available about avalanche hazards?” | `search_layers` | 12.93 s | **Pass.** Returned relevant avalanche, slope, and snow layers; four layer names became inline controls. |
| T02.1 | “Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.” | `geocode_location` | 6.07 s | **Pass.** Exact match; WGS84 `7.451352, 46.927937` and LV95 `2'600'968.69 / 1'197'426.89`. |
| T02.2 | “Show me on the map.” | `geocode_location` → `display_layer` | 7.48 s | **Pass.** Returned one personalized point, no nationwide address layer. The separate UI smoke test confirmed add and remove. |
| T03 | “Describe the layer `ch.swisstopo-vd.stand-oerebkataster`, including its fields, owner, map service, legend, and download options.” | `describe_layer` | 14.33 s | **Partial.** Metadata and all requested fields were correct, including both extract fields, but the answer said the title was clickable while no catalogue-layer reference was emitted. |
| T04 | “At Seftigenstrasse 264, Wabern, return the complete ÖREB record, EGRID, PDF extract, online extract, and prepare the exact parcel polygon for the map.” | `geocode_location` → `search_layers` → `identify_at_point` → `display_layer` | 22.82 s | **Pass.** Correct EGRID, both links, authority, one exact parcel polygon, and one separate official ÖREB layer control. |
| T05 | “Find the canton of Zug and show me which administrative level was selected.” | `search_locations` → `display_division` | 8.69 s | **Pass.** Distinguished canton, commune, and locality; selected `kanton`. It additionally prepared the canton boundary. |
| T06 | “Show the boundary of the canton of Zug on the map.” | `display_division` | 4.25 s | **Partial.** The correct one-feature personalized polygon/card was returned, but the prose said it was already displayed; the user still had to click **Show result on map**. |
| T07 | “Find every municipality inside the true boundary of the canton of Zug, not merely inside its bounding rectangle.” | `search_locations` → `search_layers` → `filter_features` → `display_division` → `analyze_features` → `display_layer` | 19.19 s | **Pass.** Real canton boundary used; exactly 11 municipality polygons returned, plus the canton boundary. |
| T09 | “For the municipalities fetched in canton Zug, calculate the count, total area, total boundary length, extent, and numeric area statistics.” | `search_locations` → `search_layers` → `filter_features` → `analyze_features` × 5 | 20.79 s | **Pass.** Count 11, area 238.73 km², boundary 290.43 km, extent, and field statistics were returned. |
| T08 | “Make the current flood warning map available to add to the map, focused on Valais, at 70% opacity.” | `search_layers` → `search_locations` → `display_catalog_layer` | 11.51 s | **Pass.** Correct official warning layer, opacity `0.7`, and Valais focus bbox. |
| T10 | “Find all municipalities in canton Zug and prepare the personalized result for the map with a blue fill at 60% opacity.” | `search_locations` → `search_layers` → `filter_features` → `analyze_features` → `display_layer` | 15.93 s | **Pass.** 11 polygons with `#0000FF` fill and `0.6` opacity. |

## Sequential results — multi-tool workflows

| ID | Workflow/query | Tools actually used | Time | Result |
|---|---|---|---:|---|
| WA.1 | Exact-address coordinates | `geocode_location` | 7.08 s | **Pass.** Exact official address and both coordinate systems. |
| WA.2 | Address follow-up: “Show me on the map.” | `geocode_location` → `display_layer` | 6.86 s | **Pass.** One personalized address point and no catalogue-layer substitute. |
| WB | Complete ÖREB extract, parcel, and nationwide availability layer | `geocode_location` → `search_layers` → `identify_at_point` → `display_layer` → `display_catalog_layer` | 22.61 s | **Pass.** EGRID `CH669746359158`, PDF, online URL, authority, one parcel polygon, and one separately labelled official layer. |
| WC | Compare flood warning, stations, runoff, and Aquaprotect in Valais | `search_locations` → `search_layers` × 4 → `display_division` → `display_catalog_layer` × 7 | 36.74 s | **Pass.** One canton boundary and seven inline official layer choices, including all four Aquaprotect return periods. |
| WD | Complete Zug municipality analysis and both personalized layers | `search_locations` → `search_layers` → `filter_features` → `display_division` → `analyze_features` × 4 → `display_layer` | 21.80 s | **Pass.** Correct 11-count statistics, municipality layer, and canton-boundary layer. |
| WE | Structured `kanton = ZG` and `gemflaeche > 1000` filtering | `search_locations` → `search_layers` → `describe_layer` → `filter_features` → `analyze_features` × 3 → `display_layer` → `display_division` | 48.02 s | **Pass.** Schema inspection preceded filtering; nine features and combined 22,576 ha were reported. The prose omitted four individual area values even though they were present and used in the aggregate. |
| WF | Analyze municipalities in the current map view | `search_layers` → `filter_features` → `analyze_features` × 2 → `display_layer` | 23.03 s | **Pass.** The frontend sent the live WGS84 bbox around Wabern and the active address-point layer; 18 intersecting municipality features were returned as a personalized result. |
| WG-en | “Show me flood hazards in Valais.” | `search_locations` → `search_layers` → `display_catalog_layer` × 3 → `display_division` | 18.58 s | **Pass.** English answer, three inline official controls, and a Valais boundary. |
| WG-de | “Zeige mir Hochwassergefahren im Wallis.” | `search_layers` → `search_locations` × 2 → `display_catalog_layer` × 2 → `display_division` | 20.59 s | **Pass.** German answer, stable official IDs, two inline controls, and a boundary. |
| WG-fr | “Montre-moi les dangers de crues en Valais.” | `search_locations` → `search_layers` → `display_division` → `display_catalog_layer` × 3 | 18.37 s | **Pass.** French answer and three inline controls. |
| WG-it | “Mostrami i pericoli di piena in Vallese.” | `search_layers` → `search_locations` × 2 → `display_division` → `display_catalog_layer` × 3 | 27.67 s | **Pass.** Italian answer and three inline controls. |
| WG-rm | “Mussa ma ils privels d'inundaziun en il Vallais.” | `search_layers` → `search_locations` → `display_catalog_layer` × 3 | 23.82 s | **Pass.** Romansh answer and three inline controls. The progress labels fall back to German, while the answer and request language remain Romansh. |
| WH | Impossible Bitcoin/Atlantis dataset | No tool call | 4.04 s | **Pass.** Explicit no-match explanation; no invented place, generated layer, or official layer. |

## Frontend map-control verification

The official-layer flow passed through the real rendered chat UI:

- A mentioned official layer name rendered as a clickable inline control.
- Clicking it opened the tooltip above the answer.
- The tooltip showed the layer type, title, attribution, and stable `ch.*` ID.
- The top-right **×** close control was present.
- The two actions were **Add map layer** and **Layer details**.
- Adding changed the first action to **Remove map layer**.
- Removing worked, and **Layer details** opened the metadata dialog.

The personalized-result flow also passed:

- **Show result on map** loaded and decoded the generated GeoParquet point.
- The button changed to **On the map**.
- The displayed-maps badge changed to `1` and one active row appeared.
- Removing the result from **Displayed maps** worked.

## Feedback-specific verification

### 1. Clickable layer names in chat

This works for results that emit catalogue references. The avalanche query rendered four inline layer controls, and the flood workflows rendered two to seven localized controls. Official catalogue layers and personalized generated results are visually and behaviorally separate.

One remaining gap was found: `describe_layer` does not itself emit a catalogue-layer reference. T03 therefore produced correct metadata but a false “you can click” sentence with no clickable control.

### 2. ÖREB extract

The reported problem is fixed end to end. Both ÖREB tests returned:

- EGRID `CH669746359158`;
- `oereb_extract_pdf` as the official PDF link;
- `oereb_extract_url` as the dynamic online extract;
- the responsible Bern authority;
- one personalized exact parcel polygon, not the municipality polygon;
- one separate official nationwide ÖREB availability layer.

## Observations and recommended follow-up

1. **Make `describe_layer` references actionable.** Add its described layer to `layer_refs`, or require `display_catalog_layer` before the answer claims the title is clickable.
2. **Correct map wording.** A `display_layer`/`display_division` result is prepared for user confirmation; the answer must say “ready to show” rather than “already displayed.”
3. **Trim structured catalogue references.** `search_layers` can contribute 4–16 references even when only 1–7 are mentioned. The frontend safely renders only mentioned titles, but filtering the protocol list to mentioned or explicitly displayed layers would be cleaner.
4. **Improve Romansh progress localization.** The Romansh answer is correct, but progress-step labels currently fall back to German.
5. **Reliability note.** An earlier warm-up attempt at T01 hit the 90-second agent timeout before any MCP tool executed. The clean full rerun completed T01 in 12.93 seconds and all 24 turns succeeded, so this was transient model/Bedrock latency rather than a deterministic MCP failure.

## Reproduction

With the local frontend, backend, MCP, object storage, and layer server running:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
python3 scripts/local_customer_acceptance.py
```

To rerun selected scenarios only:

```bash
SGS_CASE_IDS=T02-geocode_location,WB-oereb-both-layer-types \
  python3 scripts/local_customer_acceptance.py
```

The harness writes its raw protocol evidence to:

```text
/tmp/sgs-local-customer-acceptance.json
```

This report covers every natural-language customer query and multi-tool workflow in `docs/mcp-tool-catalog.md`. Direct low-level MCP JSON validation cases are covered separately by the automated MCP/backend test suites; they are not browser chat queries.
