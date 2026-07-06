# Model & hosting cost — SGS LLM

A cost model for the agent backend's language model, at the scale a national geodata
portal actually runs — and how to keep the bill down. It sizes the workload from
portal traffic, prices each hosting option (managed API, managed open-weight, and an
on-premise GPU rack), shows where each one wins, and lists the levers that move the
number by 10–100×.

**On precision.** These are **order-of-magnitude** figures, not franc-precise budgets.
At this stage the goal is to know whether the answer is "hundreds", "thousands", or
"millions" of CHF per month — and which design choices move it between those bands.
The ranges tighten once the system is live and we replace assumptions with logged
usage. All prices are **public USD list prices** (mid-2026); list price is an upper
bound — real Bedrock cost is lower with committed-use discounts and credits.

**Two horizons.** Keep these separate — they have different answers:

| Horizon | Scale | What it decides |
| --- | --- | --- |
| **Pilot** | ~100 conversations/day (~300 turns/day) | Feasibility and quality. Cost is negligible here (tens of $/month even on the frontier model). |
| **Production** | portal-scale, thousands–tens of thousands of conversations/day | The go/no-go economics. This is where model and hosting choice matter. |

The pilot tells us nothing about cost; **this document is mostly about production.**

---

## 1. The scale question

**The unit that drives cost is a *turn*** — one user question and the assistant's answer.
Count it up the chain:

```
portal hits/year  ─►  human sessions  ─►  conversations/day  ─►  turns/day
(tens of millions)    (a fraction —       (a fraction of         = conversations/day
                       much traffic is     humans start a chat)     × turns/conversation
                       automated: tiles,                            ← THE COST DRIVER
                       API clients, bots)
```

- A **conversation** is one chat session; a **turn** is one question answered within it.
- **turns/day = conversations/day × turns/conversation.** This — not portal hits, not
  visitor counts — is what the bill scales with.
- For an *agent*, one turn is **several model calls** internally (the tool-calling loop);
  that multiplication lives in the tokens-per-turn number (§2), not in the turn count.

A national portal at the scale of map.geo.admin.ch handles on the order of **tens of
millions of hits per year (~40–80k/day)** — but that is the wrong base to cost against:
a large share is **automated** (tile fetches, API clients, crawlers) that never reaches a
chatbot, and only a fraction of *human* visitors start a conversation. So we cost against a
**range of conversations/day × turns/conversation** and let the real adoption rate, once
measured, place us on it. Scenarios used throughout this document:

| Scenario | Conversations/day | Turns/conversation | **Turns/day** |
| --- | --- | --- | --- |
| **Pilot** | 100 | 3 | **300** |
| **Low** | 1,000 | 3 | **3,000** |
| **Medium** | 5,000 | 4 | **20,000** |
| **High** | 10,000 | 6 | **60,000** |
| **Stress** | 20,000 | 10 | **200,000** |

The **Stress** row is the heaviest case put on the table — 20,000 conversations/day of 10
turns each. Both *conversations/day* and *turns/conversation* are adoption unknowns; the
table spans two orders of magnitude in turns/day precisely because they are.

**Frame for "acceptable".** Whatever the LLM costs, it should be a **small fraction of the
portal's total operating budget** — the AI layer is an add-on to a service that already
costs far more to run. That is the yardstick to hold every option against below.

---

## 2. What one turn costs, in tokens — and the cost formula

The whole model is one formula, applied per scenario:

```
monthly $  ≈  30 × turns/day × ( eff_in × price_in  +  out × price_out ) / 1,000,000
eff_in      =  raw_in × ( (1 − c) + c × 0.1 )     # caching: a cache read costs 0.1× fresh input
turns/day   =  conversations/day × turns/conversation
```

Four workload parameters drive it (the rest is just model prices):

| Parameter | Meaning | Planning range | Note |
| --- | --- | --- | --- |
| `raw_in` | input tokens **per turn**, summed over every model call in the agentic loop | **light ~1.5k · lean ~5k · rich ~15k** | **the #1 unknown — measure it first** |
| `out` | output tokens per turn | ~200–400 | barely moves the total |
| `c` | cacheable fraction of input (static system prompt + tool schemas) | ~0.5–0.7 | the dominant cost lever |
| prices | per-model $/1M input & output | §3 | Claude · managed-open · on-prem-flat |

**Why `raw_in` spans 10×.** The workload is **input-token-dominated** — a large, repeated
prefix (system prompt + tool schemas + tool results) goes *in*, a short answer comes *out*
(ratio > 20:1). How big that prefix is depends entirely on how agentic the turn is:

- **~1.5k (light)** — a single model call answering from a static prompt: a help/FAQ turn.
- **~5k (lean)** — a short tool-using turn: one or two tool calls, modest results fed back.
- **~15k+ (rich)** — a full agentic turn over the ~1,000-layer catalog: catalog search +
  layer schema + geocode + identify/filter, several model calls each re-sending the tool
  schemas and accumulating tool results.

`raw_in` is therefore **the single number that decides whether the answer is thousands or
hundreds of thousands per month**, so we will **log it the moment the agent runs on real
Swiss-geodata queries** and quote a range until then. `out` barely matters; caching (`c`)
matters most on the frontier tiers, where the fresh prefix is expensive.

### Why two honest estimates diverge — and how to read them

The same system can be costed correctly and land an order of magnitude apart, because
**two inputs move the answer more than anything else: `raw_in` and `turns/day`.** A worked
reconciliation, since this exact question came up:

- **Estimate 1 — light bot, modest volume.** ~10,000 conversations/day × ~3 turns at
  ~1,200 input tokens/turn ⇒ ~30,000 turns/day ⇒ **~$1–6k/month** on Haiku/Sonnet with
  caching. Correct — for a **single-call FAQ bot**.
- **Estimate 2 — same light tokens, heavier volume.** 20,000 conversations/day × 10 turns
  ⇒ **200,000 turns/day** at ~1,200 tokens/turn ⇒ **~$13k (Haiku) to ~$26k (Sonnet 5) per
  month.** Also correct — same token load, ~7× the turns.

Both hold *at ~1,200 input tokens/turn* — a **FAQ/help bot**. SGS-LLM is an **agentic
geodata assistant**: to answer "show the flood zones near Bern" it searches the catalog,
reads layer schemas, geocodes "Bern", identifies/filters features — several model calls,
each re-sending tool schemas and accumulating tool results. That puts `raw_in` in the
**lean-to-rich (5–15k+) range, not 1.2k**. Not a pricing error — a **heavier product**.

Sensitivity at the **Stress** anchor (**200,000 turns/day**, `out`=300, list price):

| `raw_in`/turn | Managed open | Haiku 4.5 | Sonnet 5* | Sonnet 4.6 | Opus 4.8 |
| --- | --- | --- | --- | --- | --- |
| **~1.2k** (FAQ) | ~$6k | ~$16k | ~$32k | ~$49k | ~$81k |
| **~5k** (lean) | ~$18k | ~$39k | ~$78k | ~$117k | ~$195k |
| **~15k** (rich) | ~$48k | ~$99k | ~$198k | ~$297k | ~$495k |
| **~15k + caching** (`c`=0.7) | ~$19k | ~$42k | ~$85k | ~$127k | ~$212k |

*Sonnet 5 = intro pricing through 2026-08-31. `out`=300; shorter (~200-token) answers shave
~15–20%, which is why the 1.2k row here reads a touch above the ~$13k/$26k in Estimate 2.*

Two readings:

- **At heavy volume the model choice is the whole game.** 200k turns/day of a *real* agent
  is **six figures/month on any Claude tier**, but **~$8–20k on a managed-open model**
  (depending on tokens and caching) — and, since that is above the on-prem crossover (§7),
  **~$5–12k flat on an on-prem rack.** Frontier/mid Claude per-token is the wrong tool at
  this scale.
- **The scary numbers need three things at once** — frontier model *and* rich tokens *and*
  no caching (bottom-right of the table). Drop any one and it falls an order of magnitude;
  the production design drops all three.

**Practical consequence:** pin down `raw_in` empirically (we log it as soon as the agent
runs) and read cost straight off the §2 formula. Until then the range is honest — and the
**production path (managed-open or on-prem + tiering + caching) stays in the
low-tens-of-thousands even at the Stress anchor**, and far less below it.

---

## 3. Model prices, and cost per turn

Prices are **list, on the Bedrock EU cross-region profile** (`eu.anthropic.claude-*`;
Claude 4.5+ on the EU profile is ~10% over global — already included). The `$/turn`
columns apply the §2 formula at the **lean** tier (`raw_in`=5k, `out`=300):

| Model | $/1M in | $/1M out | $/turn (list) | $/turn (`c`=0.7) |
| --- | --- | --- | --- | --- |
| **Managed open — light** (Llama 4 Scout / Maverick) | ~$0.20 | ~$0.60 | ~$0.0012 | ~$0.0006 |
| **Managed open — strong** (GLM / DeepSeek / Mistral Large 3) | $0.50 | $1.50 | ~$0.0030 | ~$0.0014 |
| **Haiku 4.5** | $1.00 | $5.00 | ~$0.0065 | ~$0.0034 |
| **Sonnet 5*** | $2.00 | $10.00 | ~$0.0130 | ~$0.0067 |
| **Sonnet 4.6** | $3.00 | $15.00 | ~$0.0195 | ~$0.010 |
| **Opus 4.8** | $5.00 | $25.00 | ~$0.0325 | ~$0.017 |

*Sonnet 5 = intro pricing through 2026-08-31 (global-only on Bedrock today — see §10).*

- **Caching cuts the Claude figure ~40–60%** — a cache read costs 0.1× the input price,
  and the big prefix repeats every call. The open rows are already tiny, so caching
  matters most on the Claude tiers.
- A capable **managed-open** model is **~5–10× cheaper than Sonnet, ~10× cheaper than
  Opus** on this workload — same Bedrock API, same EU profile, only the model ID changes.

---

## 4. Production cost across the ladder

Monthly cost from the §2 formula at the **lean tier** (`raw_in`=5k, `out`=300, **caching
on**, `c`=0.7), across the §1 scenario ladder (column header = turns/day):

| Model | Pilot (300) | Low (3k) | Medium (20k) | High (60k) | Stress (200k) |
| --- | --- | --- | --- | --- | --- |
| **Managed open — strong** | ~$12 | ~$120 | ~$830 | ~$2.5k | ~$8.2k |
| **Haiku 4.5** | ~$30 | ~$300 | ~$2.0k | ~$6.0k | ~$20k |
| **Sonnet 5*** | ~$60 | ~$600 | ~$4.0k | ~$12k | ~$40k |
| **Sonnet 4.6** | ~$90 | ~$900 | ~$6.0k | ~$18k | ~$60k |
| **Opus 4.8** | ~$150 | ~$1.5k | ~$10k | ~$30k | ~$100k |

At the **rich** tier (`raw_in`=15k) multiply by ~2–3×; at the **light/FAQ** tier
(`raw_in`=1.5k) roughly halve — the §2 table has the exact rich figures.

**What the ladder shows:**

- **Below the High rung** (≤60k turns/day ≈ 10k conversations/day × 6 turns), a
  **managed-open model runs the whole service for ~$2.5k/month or less** — a small
  fraction of the portal budget, zero infrastructure, EU residency. Even mid Claude
  (Sonnet) is only low-five-figures here.
- **At the Stress rung** (200k turns/day), per-token pricing separates hard: managed-open
  ~$8k, but every Claude tier is **$20–100k/month**. This is where **on-prem** (§6–§7)
  takes over: a flat **~$5–12k/month** rack undercuts everything.
- **The frontier model (Opus) is never the production default** — it is a pilot/quality
  and hard-tail tool. At Stress it alone is ~$100k/month (~$1.2M/year).

---

## 5. Hosting options — the real spectrum

"Self-hosting on Bedrock" is a contradiction: **Bedrock is a managed service — you never
run the GPUs.** There are four real options, from zero-ops to full-control:

1. **Managed foundation models (serverless, per-token).** Claude (Opus 4.8, Sonnet
   4.6/5, Haiku 4.5) *and* managed open-weight models — Bedrock added a set of
   open-weight models in 2026 (**DeepSeek, GLM, Qwen, Kimi**, alongside **Llama** and
   **Mistral**). You call an API; AWS runs the hardware. Low-effort path for both Claude
   and strong open models.
2. **Bedrock Custom Model Import (bring-your-own weights, still managed).** Upload
   weights for a **supported architecture** (Mistral / Mixtral / Llama 2–3.3 / GPT-OSS —
   **not** the GLM or DeepSeek architectures) and AWS serves them. Billed in **Custom
   Model Units** (import free; pay per active model copy, auto-scaled). Limits: weights
   < 200 GB, context < 128k. Use for a fine-tuned open model without running infra.
3. **True self-hosting on cloud GPU (EC2).** You own the vLLM/TGI stack, scaling, and
   uptime on `g6e`/`p5`-class instances. Fixed monthly GPU bill; still on AWS
   (US-managed) infrastructure.
4. **On-premise GPU rack (§6).** Hardware you own, in a data centre you control. The
   only option that delivers **full Swiss data sovereignty** (air-gap capable) and turns
   cost into **capex + electricity** — flat, independent of query volume.

Options 1–2 dominate below production scale. Option 4 becomes economical (and is the
sovereignty play) at high sustained volume. Option 3 is mostly a stepping stone to 4.

---

## 6. The on-premise GPU rack

At production scale the most important property of on-prem is that **cost stops scaling
with usage**. A rack is a fixed capex plus electricity; whether it serves 3,000 or 200,000
turns/day, the bill is the same until you saturate its throughput. That **bounds the worst
case** — it can never reach the six-figures/month of per-token frontier API, because it is
power and hardware, not per-token.

Two rack tiers, depending on which model tier the quality floor demands:

| Tier | Hardware (illustrative) | Capex | Runs | Amortised cost/month* |
| --- | --- | --- | --- | --- |
| **Small rig** | 1–2× high-end GPU (e.g. H100 80 GB, or 2× L40S / A100) | **~$20–30k** | Quantized/distilled **32–110B** open model (DeepSeek-distill, GLM-4.5-Air, Qwen3, Llama 4 Scout) | **~$5,000** |
| **Flagship rig** | 8× H100 (640 GB) | ~$250k+ (or ~$40k/mo rented cloud) | Full flagship MoE (**DeepSeek V4, GLM-5.2, Mistral Large 3, Llama 4 Maverick**) | **~$10–12k** (on-prem) / ~$40k (cloud-rented) |

*Amortised = capex spread over ~3 years + **opex ~$50k/year** (electricity, hosting,
and a fraction of an engineer's time for serving, patching, and model updates). All-in
opex stays comfortably under $100k/year for the small rig.

**Serving stack:** vLLM (continuous batching, quantization, OpenAI-compatible API). A
**request queue** in front of the rack is what makes fixed hardware absorb bursty load
(see §7) — you serve a queue, not 50,000 concurrent requests.

**When on-prem is the right call:**
- **Very high sustained volume** — above the crossover in §7, the flat cost beats
  per-token pricing.
- **Hard sovereignty requirement** — Swiss-only / air-gapped data handling that even the
  EU Bedrock profile can't satisfy. On-prem is the only option that fully removes the
  US-managed-cloud dependency.

**Caveats:** the small rig runs a *capable but not frontier* open model — it accepts the
capability floor of a 32–110B model (mitigated by good tool design, §8). The flagship rig
removes that ceiling but is a six-figure capex decision. Ops burden is real and recurring.

---

## 7. Managed API vs on-premise — the decision

The small on-prem rig is **~$5,000/month flat**. Against per-token managed pricing (lean
tier, caching on) that sets a **crossover volume** — below it, managed is cheaper *and*
zero-ops; above it, on-prem wins:

| Compared against | Crossover (≈ where on-prem gets cheaper) |
| --- | --- |
| Managed open — strong | ~120,000 turns/day |
| Haiku 4.5 | ~50,000 turns/day |
| Sonnet 5 | ~25,000 turns/day |
| Sonnet 4.6 | ~17,000 turns/day |
| Opus 4.8 | ~10,000 turns/day |

Read as a decision matrix (turns/day = conversations/day × turns/conversation):

| Sustained volume | Recommended | Why |
| --- | --- | --- |
| **Pilot–Low** (≤3k turns/day) | **Managed Claude → managed open** on Bedrock | Cheapest and zero-ops; frontier for quality, open to cut cost |
| **Medium–High** (20–60k turns/day) | **Managed open, tiered** | Still cheapest, still zero-ops; ~$0.8–2.5k/month |
| **Stress** (>~100k turns/day) | **On-prem GPU rack** *or* managed-open | Flat ~$5–12k/month rack beats every Claude tier and undercuts even managed-open at the top |
| **Any volume + hard sovereignty** | **On-prem GPU rack** | Only option with full Swiss data control |

**The strategic point:** managed open on Bedrock covers essentially every realistic
adoption scenario cheaply, and the on-prem rack is the **ceiling** — it caps the
worst-case cost at a flat low-five-figures/month and simultaneously answers the
sovereignty question. The frontier API sits *outside* this decision as a pilot/quality
tool, not a production server.

---

## 8. The cost levers

At production scale the levers matter more than the sticker price — each moves the bill
by a large factor. In rough order of impact:

1. **Model choice + tiering — the biggest lever (~10–20×).** Moving off the frontier is
   most of the saving. Don't use one model for everything: **route** the easy majority to
   a small/open model and reserve a capable model for the hard multi-tool tail. An eval
   over real Swiss-geodata questions (all five languages) finds where the floor sits.
2. **Prompt caching (~40–60% off the Claude bill).** The large input prefix (`c` in the §2
   formula) repeats every call; cache reads cost 0.1× fresh input. Highest-value lever on
   any Claude tier.
3. **Answer / response caching.** Many portal questions are **not unique** — the same
   popular layers and places recur. A semantic cache that deflects repeat questions cuts
   the *number of model calls*, which compounds with every other lever. High value
   precisely because portal traffic is repetitive.
4. **Queuing.** Decouples concurrency from cost. Instead of provisioning for peak
   concurrency (or paying per-token for a burst), a queue spreads load across fixed GPU
   capacity — essential for on-prem, useful for smoothing managed spend.
5. **Context-window limits.** The bill is input-dominated, so capping question
   length/turn depth directly caps cost. One deep vs. shallow question is a ~100× swing —
   bound it.
6. **Adoption realism.** Don't cost the whole 40–80k/day of portal hits as chatbot
   conversations — most are automated and never reach the assistant. Size against measured
   chatbot turns/day (conversations × turns), not portal hits.
7. **Batch API (50% off).** For offline/non-interactive jobs only; not for interactive
   chat.

Beyond these, prompt- and tool-engineering reduce token use further; those are tuned
during implementation against measured traces.

---

## 9. Do we need a large model?

Not a single large model for everything — and not "no model". You always need an LLM to
choose tools and build valid arguments (layer IDs, bounding boxes). The real question is
the **capability floor**, and it splits by query type:

- **Simple / short / single-tool turns** run fine on a small model (Haiku-class or a
  small open model). These are the majority.
- **Complex multi-tool spatial reasoning and large-context / semantic-search turns** —
  the minority tail that invokes many tools or needs a big context window — need a
  capable model; small models regress here (wrong tool, invalid bbox, weaker
  multilingual incl. **Romansh**).

So the answer is **model tiering / routing**, and it interacts with tooling: **the model
requirement shrinks as the MCP server's tools improve.** If the server exposes a good
`search_catalog` / `get_layer_schema` tool instead of forcing the model to know ~1,000
layer IDs, a smaller model can delegate the lookup. Design the connector well and the
required model tier drops — which directly lowers the cost band you land in above.

---

## 10. Data residency & sovereignty

The app is deployed in **Europe (Frankfurt), `eu-central-1`**. Claude is reached through
the Amazon Bedrock **EU cross-region inference profile** (`eu.anthropic.claude-*`), which
keeps every request within EU regions — data stays in the EU, and Bedrock retains no
prompts or outputs by default. This gives EU residency without self-hosting.

- EU inference profiles exist for **Opus 4.x, Sonnet 4.x, Haiku 4.5**; the newest models
  may ship global-only first (e.g. Sonnet 5). If EU-only routing is a hard requirement,
  model choice is limited to what has an `eu.` profile, and that regional profile adds
  ~10% over global.
- **Zurich (`eu-central-2`)** is the intended region for the production compute/data path
  if in-country Swiss residency is needed; it is opt-in (must be enabled on the account),
  and Claude would still be reached through the EU inference profile. See
  [`deployment.md`](../deployment.md#region-note).
- **Full sovereignty** (Swiss-only, air-gap capable) is the domain of the **on-prem GPU
  rack (§6)** — the only option that removes the US-managed-cloud dependency entirely.
  This is a distinct, larger work package, justified by regulation rather than cost.

---

## 11. Recommendation

Start at the quality ceiling, then walk **down the cost curve**, gating each step on the
same eval. This is a config swap (Bedrock `InvokeModel` + inference profile) until the
last step, so nothing locks us in:

1. **Pilot — Claude Opus 4.8, single tier** (`eu.anthropic.claude-opus-4-8`). Establishes
   quality and builds the eval set of real Swiss-geodata questions (all five languages).
   ~$50/month at pilot scale — cost is not the constraint here.
2. **Model tiering.** Route simple turns to Haiku (or a small open model); keep the
   complex tail on Sonnet/Opus. Biggest single saving, no infra change.
3. **Managed open model** (strong open-weight on Bedrock EU — GLM / DeepSeek / Mistral
   Large / Qwen). ~10–20× cheaper; measure the quality gap against the eval. **This is the
   likely production default** — it keeps the bill at a small fraction of the portal
   budget across every realistic adoption scenario, with zero infrastructure.
4. **On-prem GPU rack** — only if (a) sustained volume climbs above the §7 crossover, or
   (b) a hard Swiss-sovereignty requirement demands it. Flat cost, bounds the worst case,
   full data control; accept the ops burden and (for the small rig) the capability floor.

Apply the cross-cutting **levers (§8)** — caching, answer-caching, queuing, context
limits — at every step; they compound.

**First concrete action — measure `raw_in`.** The whole range in this document collapses
to a figure once we log the real **input tokens per turn** on Swiss-geodata queries (§2).
It is the fastest, cheapest thing we can do to sharpen the budget, and it happens
naturally as soon as the pilot agent runs.

**Volume-dependent conclusion:**

- **Up to the High rung (~60k turns/day):** a **managed-open model on Bedrock** runs the
  whole service for **~$2.5k/month or less** — zero-ops, EU residency. The clear default.
- **At the Stress rung (~200k turns/day):** per-token Claude is $20–100k/month — out. The
  answer is **managed-open (~$8k) or an on-prem rack (~$5–12k flat)**; on-prem also caps
  the worst case and delivers full Swiss sovereignty.

**Bottom line for the go/no-go:** frontier-API-at-full-scale is off the table
(six-figures/month), but that was never the plan. A **managed open model** serves portal
scale for **single-digit thousands of $/month up to heavy adoption**, and an **on-prem
rack** caps the worst case at a flat **~$5–12k/month** while delivering sovereignty. The
economics work; the remaining unknowns are **adoption** (conversations × turns) and
**`raw_in`**, both of which only real usage will settle.

---

## Sources

- [Anthropic model pricing](https://platform.claude.com/docs/en/about-claude/pricing)
  — per-model prices, prompt-caching multipliers, regional +10%, batch discount
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) ·
  [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)
- [Bedrock Custom Model Import](https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-import-model.html)
  · [Custom Model Unit cost](https://docs.aws.amazon.com/bedrock/latest/userguide/import-model-calculate-cost.html)
  · [Bedrock adds open-weight models (2026)](https://aws.amazon.com/about-aws/whats-new/2026/02/amazon-bedrock-adds-support-six-open-weights-models/)
- [Cross-region inference for EU data processing (AWS Switzerland blog)](https://aws.amazon.com/blogs/alps/unlocking-ai-flexibility-in-switzerland-a-guide-to-cross-region-inference-for-eu-data-processing-and-model-access/)
- [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/) ·
  [g6e.xlarge](https://instances.vantage.sh/aws/ec2/g6e.xlarge) ·
  [p5.48xlarge (8× H100)](https://instances.vantage.sh/aws/ec2/p5.48xlarge)
- [vLLM](https://docs.vllm.ai/) — production serving stack for self-hosted / on-prem
- EU inference-profile availability and Frankfurt (`eu-central-1`) GPU rates
  cross-checked against the live AWS APIs, 2026-07.
