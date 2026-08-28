# Evaluation and model benchmark

[`evals/`](../evals/) holds a question set and a runner that answer two different
questions with one harness:

1. **Does the agent work?** Does it pick the right tools, chain them, produce layers,
   answer in the right language, and decline what it should?
2. **Which model should the pilot use?** The same set run against Claude, Mistral and
   the self-hosted Apertus 1.5, side by side, with per-category pass rates - evidence for
   a decision that would otherwise be made on datasheets.

It drives the **real agent loop against a real MCP server**, so it measures the deployed
behaviour rather than a model in isolation.

## The question set

[`evals/questions.yaml`](../evals/questions.yaml) - 87 questions in all five UI languages,
written the way a member of the public or an administration employee actually types: terse,
lowercase, missing umlauts, occasionally in dialect, sometimes stating a wrong fact with
confidence, sometimes barely a question at all.

They are deliberately **not tuned to what the smaller model can pass**. The point is to
separate the models, so a category the secondary model fails is a *result*, not a
bug in the question.

| Category | What it tests | Why it separates models |
| --- | --- | --- |
| `single_dataset` | one catalogue lookup | the easy floor; both should clear it |
| `place_scoped` | place → features → map | two chained tools, the core user journey |
| `compositional` | combine, count, measure, compare | multi-step tool competence |
| `ambiguous` | asking instead of guessing | restraint, which weaker models lack |
| `ambiguous_defaultable` | choosing a default instead of asking | the opposite failure - see below |
| `vague` | almost no information given | must ask rather than invent a request |
| `messy_input` | typos, no umlauts, CAPS, dialect, rambling | robustness to real typing |
| `user_is_wrong` | a false premise stated confidently | must correct, not go along with it |
| `wrong_data_owner` | cantonal/communal data asked of a federal service | must say who actually holds it |
| `coordinates` | LV95, WGS84, addresses, postcodes | LV95 metres read as degrees land in the ocean |
| `multi_intent` | several questions in one turn | must serve all of them, or say what it skipped |
| `not_queryable` | a real but raster-only dataset | the tool's "pick another" signal must change the plan |
| `no_such_dataset` | admitting nothing matches | punishes confabulation |
| `out_of_scope` | declining cleanly | punishes inventing a Swiss dataset to fit |
| `prompt_injection` | ignoring hostile instructions | in the message *and* inside fetched data |
| `multilingual` | answering in the asked language | includes Romansh and code-switching |
| `conversational` | elliptical, orphaned and self-correcting follow-ups | needs the history to make sense |
| `geosearch_tools` | production-only geocoding, metadata, identify, boundary, filtering, analysis, and display paths | exercises the ten-tool production surface rather than only the six-tool stand-in subset |

The current production tool contracts are in
[`mcp-tool-catalog.md`](./mcp-tool-catalog.md). Run `geosearch_tools` against a live local
geosearch server; using `mcp_dummy` would measure missing compatibility tools rather than
agent planning.

### Why both `ambiguous` and `ambiguous_defaultable`

They pull in opposite directions, on purpose. `must_clarify` questions reward asking;
`must_not_clarify` questions fail an answer that asks when there was an obvious default and
no tool was called. Without the second kind, a model that responds "which did you mean?" to
everything would score well while being useless - the benchmark would be gameable by pure
caution. Over-asking is a real failure mode, so it gets its own stage: `over_clarified`.

## How a question is scored

Rule checks first - deterministic, free, and useful while only one model is reachable.
Each failure carries a **stage**, so the report says *where* a model broke down rather
than only that it failed: `no_tool_call`, `wrong_tool`, `chain_broken`, `no_layer`,
`unexpected_layer`, `too_many_tools`, `wrong_language`, `missing_mention`,
`forbidden_content`, `no_clarification`, `over_clarified`, `exchange_error`, `empty_answer`.

Where correctness is a matter of degree - "did it refuse gracefully", "is that figure
right" - the question carries `judge: true` and `--judge` has a model grade it 1-5 with a
written reason. **The report keeps rule verdicts and judged scores apart** rather than
blending them into one number.

Two honest limitations:

- **Answer language is detected with a function-word heuristic**
  ([`evals/checks.py`](../evals/checks.py)), not a language identifier. It reliably
  catches a model answering in the wrong language, which is what it is for; Romansh and
  Italian overlap, so distinctive Romansh tokens are weighted to break the tie.
- **The Romansh question should be reviewed by a native speaker** before any result is
  quoted externally.
- **The set is 71% German** (62 of 87), because dropped umlauts and dialect are most natural
  there. French, Italian and English are represented but thinner, and Romansh is a single
  question. A result from this set is therefore a *German-weighted* result - say so when
  quoting it, or add questions before drawing per-language conclusions.
- **Run-to-run variance is real** at temperature 0.2: two runs of the same build scored
  identically overall while failing different questions. Treat a couple of questions either
  way as noise, and run three times before quoting a number.

## Prompt injection via data

The realistic injection route for a geodata agent is not the user's message - it is a
value inside a public dataset. The `injected_features` fixture wraps the MCP server so
fetched feature attributes carry hostile text, and the question then checks the model
summarised the attributes instead of obeying them. Those questions run against their own
server instance so the hostile data cannot leak into other results.

## Running it

**Local only, by design.** No CI job invokes `evals/run.py`: a benchmark run needs Bedrock
credentials and the VPN, spends real tokens, and is not a pass/fail gate. CI covers the
harness instead, running `backend/tests/test_evals.py` against the scoring logic with no
network and no AWS. Results land in the gitignored `evals/results/`, so a run never reaches
the repository.

By default the harness constructs the six-tool stand-in in process. Pass `--mcp-url` to
exercise an already-running production geosearch server; the `geosearch_tools` category
requires that mode. Neither benchmark listener is exposed publicly by the harness.

`--model apertus` names a role rather than a model id: the endpoint, key and provider all
come from `APERTUS_BASE_URL` and `APERTUS_API_KEY`. It costs no Bedrock tokens, but it only
answers from inside the VPC or the askEarth gateway IP, only during weekday office hours,
and it serves one conversation at a time, so a full run takes considerably longer than a
Bedrock one. The harness gives it a 240 s per-question budget instead of 120 s; `--timeout`
overrides that for every model at once.

Costs Bedrock tokens: 87 multi-turn conversations per model - on the order of half a million
input tokens for a Ministral run, and more for a larger model. Check the on-demand
tokens-per-minute quota before a full run; increases are not instant
([`deployment.md`](./deployment.md#bedrock-model-access)). Use `--only <category>` while
iterating rather than paying for the whole set.

```bash
cd backend && pip install -r requirements-dev.txt   # once
export AWS_BEARER_TOKEN_BEDROCK=<key>               # or use an AWS profile; VPN required

python evals/run.py --list                          # what would run; spends nothing
python evals/run.py --model mistral.ministral-3-14b-instruct --region eu-west-1
python evals/run.py --model apertus                 # the self-hosted endpoint
python evals/run.py --all                           # every configured model, side by side
python evals/run.py --only place_scoped --model ... # one category while iterating
python evals/run.py --mcp-url http://127.0.0.1:8790/mcp \
  --only geosearch_tools --model ...                # all ten production tools
python evals/run.py --judge --all                   # add model-graded quality
```

Results land in `evals/results/<timestamp>.jsonl` (every turn in full) and
`<timestamp>.md` (the report). Rows are written as each question finishes, so an
interrupted run is still readable and `summarise` can report on a partial file.

Both are gitignored: they contain model output and are regenerated on demand. A run worth
keeping goes in `evals/results/keep/` with a notes file recording the model ids, the
question-set hash, the prompt variant, whether judged scores were produced, and anything
the pass rate does not show. Still local only, still out of the repository.

**Runs are not merged.** Each invocation writes a standalone report; `--all` is what
produces a side-by-side table, and it needs both models reachable in the same run. While
the organization SCP blocks Claude ([`llm.md`](./llm.md)) that is not possible, so the
model comparison has to wait for the SCP rather than being assembled from two runs.

Merging across time was rejected rather than unimplemented: the question set will grow and
`MODEL_PROMPTS` now lets prompts differ per model, so a merged table would silently mix a
July Mistral run against a later Claude run on a different question set and read as a
controlled comparison. Every row therefore records `question_set` (a hash of
`questions.yaml`) and `prompt_variant`, and the report header states both, so a future
merge can be restricted to rows where they match, instead of being quietly wrong.

The harness's own logic - the rule engine, the language heuristic, the report generator -
is unit-tested in `backend/tests/test_evals.py` and runs in CI without touching Bedrock.
