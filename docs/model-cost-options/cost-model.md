# Model & hosting cost — SGS LLM

A cost comparison for the agent backend's language model, and how to keep the bill
down. It answers four questions — what Claude costs, what an open model costs,
whether we need a large model, and whether a self-hosted small model would be
enough — then covers the hosting spectrum, a 100-user estimate, and the levers
that cut cost.

All figures are **public USD list prices** (mid-2026), for illustration. List
price is an upper bound: real Bedrock cost is lower with committed-use discounts
and credits. Confirm the exact rate for the pinned model and region in the AWS
console before quoting a budget.

## The four questions, answered

1. **What does Claude via Bedrock cost?** About **$0.03–0.15 per question**
   (Haiku → Opus, incl. the EU +10% below) — so **~$30–150 per 1,000 questions**,
   and prompt caching cuts the Claude figure a further ~40–60%. For 100 users at
   moderate use that is roughly **$330/month (Haiku) to $1,650/month (Opus)**.
2. **What would an open model cost?** A **managed** open-weight model on Bedrock
   runs ~**$0.01 per question** (~$110/month at 100 users, moderate) — about
   **10× cheaper than Sonnet, ~15× cheaper than Opus**, on the same API and EU
   profile. "Open" does **not** mean "self-hosted": the cheapest open option is
   still managed by Bedrock.
3. **Do we really need a large model?** Not one model for everything — use
   **model tiering**: a small, cheap model for the many simple turns, a capable
   model for the minority of queries that are complex multi-tool or large-context
   reasoning. An **eval** finds where the floor is.
4. **Would a self-hosted small model be enough?** A $1–5k budget self-hosts only
   a **7–70B** model, which sits **below the capability floor** for the hard
   queries. The strong open models (GLM, DeepSeek, Mistral Large, Llama Maverick)
   are ~$40k/month-to-self-host flagships — but are cheap **managed** on Bedrock.
   Managed wins below ~100,000 questions/month.

## How much a question costs, in tokens

The backend runs a **stateless agentic loop**: every turn re-sends the full
conversation history, the map context, the system prompt, and the tool schemas,
and the model calls tools a few times before it answers. So one user question is
several model calls with growing input.

This workload is **input-token-dominated**: a large, repeated prefix (system
prompt + tool schemas + tool results) goes *in*, and a short answer comes *out*.
A realistic shape for an agentic geodata assistant is **~25,000 input + a few
hundred output tokens per question** — an input:output ratio well over 20:1.

Two consequences:
- **Caching is the dominant lever**, because most of that 25k input repeats every
  call (see [Keeping the cost down](#keeping-the-cost-down)).
- **Output price barely matters** — optimise the input side.

Treat 25k/500 as a planning estimate; replace it with logged token counts once the
backend runs on Bedrock. Only the numbers change, not the method.

## Hosting options — the real spectrum

"Self-hosting on Bedrock" is a contradiction: **Bedrock is a managed service — you
never run the GPUs.** There are three real options:

1. **Managed foundation models (serverless, per-token).** Claude (Opus 4.8, Sonnet
   4.6 / 5, Haiku 4.5) *and* managed open-weight models — Bedrock added a set of
   open-weight models in 2026 (e.g. **DeepSeek, GLM, Qwen, Kimi**, alongside
   **Llama** and **Mistral**). You call an API; AWS runs the hardware. This is the
   low-effort path for both Claude *and* strong open models.
2. **Bedrock Custom Model Import (bring-your-own weights, still managed).** Upload
   weights for a **supported architecture** (Mistral / Mixtral / Llama 2–3.3 /
   GPT-OSS — **not** the GLM or DeepSeek architectures) and AWS serves them.
   Billed in **Custom Model Units** (import is free; you pay per active model copy,
   auto-scaled, in 5-minute increments). Limits: weights < 200 GB, context < 128k.
   Use this for a fine-tuned open model without running infrastructure.
3. **True self-hosting on EC2 GPU.** You own the vLLM/TGI stack, scaling, and
   uptime on `g6e`/`p5`-class instances. The only real "self-host" — and the only
   one where a rack/GPU budget is the constraint (see
   [Self-hosted small model](#would-a-self-hosted-small-model-be-enough)).

## What each option costs

### Claude via Bedrock

Per-1M list price (Bedrock matches the Anthropic API):

| Model | Input /1M | Output /1M | ~Per question | ~Per 1,000 q (EU) |
| --- | --- | --- | --- | --- |
| Opus 4.8 (frontier) | $5 | $25 | ~$0.15 | ~$150 |
| Sonnet 4.6 (mid) | $3 | $15 | ~$0.09 | ~$91 |
| Haiku 4.5 (small) | $1 | $5 | ~$0.03 | ~$30 |

- **EU data residency: +~10%.** The EU cross-region inference profile (`eu.`) we
  use is a regional endpoint, which for Claude 4.5+ costs ~10% more than global.
  (Per-question figures above already include it.)
- **Prompt caching cuts input ~40–60%.** A cache read costs 0.1× the input price;
  because the big input prefix repeats every call, most input becomes a cache read.
- **Sonnet 5** is cheaper right now ($2/$10 introductory to 2026-08-31) but is
  **global-only on Bedrock today** — not usable under EU-only routing yet.

### Open model via Bedrock (managed)

Same Bedrock API and EU profile — only the model ID changes. No GPUs to run.

| Managed open model | Input /1M | Output /1M | ~Per question |
| --- | --- | --- | --- |
| Light (Llama 4 / Mistral Small) | ~$0.24 | ~$0.97 | ~$0.007 |
| Strong (Mistral Large 3 / GLM) | ~$0.5 | ~$1.5 | ~$0.013 |

A capable managed open model is **~10× cheaper than Sonnet** for this workload,
with the same operating model.

### Self-host on EC2 GPU

Self-hosting swaps per-token cost for a **fixed monthly GPU bill** — the same
whether the app is busy or idle. Real Frankfurt (`eu-central-1`) on-demand rates:

| Instance | GPU | Fits | 24×7 /month | 1-yr commit |
| --- | --- | --- | --- | --- |
| g5.xlarge | A10G 24 GB | 7–8B model | ~$918 | ~$550 |
| g6e.xlarge | L40S 48 GB | ≤~30B (quantized) | ~$1,699 | ~$1,020 |

Not in the sticker price: serving, scaling, patching, model updates, monitoring,
on-call — recurring engineering time.

**Break-even vs a managed open model (~$0.01/question):** about **100,000+
questions/month** before self-hosting is even on price — and that ignores the ops
load. Below that, managed is cheaper *and* zero-ops.

## Cost at 100 users

Monthly cost = questions/month × cost-per-question. For **100 users** over ~22
workdays, at three usage levels (list price; caching not yet applied):

| Option | ~$/question | Light (2/day → 4,400 q) | Moderate (5/day → 11,000 q) | Heavy (10/day → 22,000 q) |
| --- | --- | --- | --- | --- |
| Opus 4.8 (EU) | $0.15 | ~$660 | ~$1,650 | ~$3,300 |
| Sonnet 4.6 (EU) | $0.09 | ~$400 | ~$1,000 | ~$2,000 |
| Haiku 4.5 (EU) | $0.03 | ~$130 | ~$330 | ~$660 |
| Managed open | ~$0.01 | ~$45 | ~$110 | ~$220 |

Notes:
- **Prompt caching cuts the Claude rows ~40–60%** — e.g. Sonnet at moderate use
  drops from ~$1,000 to ~$450–600/month.
- **List price only** — real Bedrock cost is lower with committed-use discounts and
  credits.
- A **fixed infra floor** (Fargate + ALB, a few hundred $/month) sits on top and
  does **not** scale with users.
- **Self-hosting** (~$1–1.7k/month fixed) is ~10–15× dearer than a managed open
  model at these volumes; it only pays off far above 100 users.

## Do we need a large model?

Not a single large model for everything — and not "no model." You always need an
LLM to choose tools and build valid arguments (layer IDs, bounding boxes). The
real question is the **capability floor**, and it splits by query type:

- **Simple / short / single-tool turns** run fine on a small model (Haiku-class or
  a small open model). These are the majority.
- **Complex multi-tool spatial reasoning and large-context / semantic-search
  turns** — the minority tail that invokes many tools or needs a big context window
  — need a capable model; small models regress here (wrong tool, invalid bbox,
  weaker multilingual incl. **Romansh**).

So the answer is **model tiering / routing**: send the easy majority to a small
model, escalate the hard tail to a capable one. Use an **eval** over real
Swiss-geodata questions (all five languages) to find where the floor sits, and
route accordingly. This captures most of the saving without a quality hit.

## Would a self-hosted small model be enough?

Two separate questions — hardware and capability.

**Hardware.** What you can self-host is set by your GPU budget:

| Budget | Hardware | Realistic model size | Examples |
| --- | --- | --- | --- |
| ~$1,000/mo AWS | 1× L40S 48 GB | 7–32B (up to 70B @ 4-bit) | Qwen3 32B, Llama 3.3 70B Q4 |
| ~$5,000 rack | ~48 GB (dual 4090) | 32B; 70B @ Q4 (tight) | Llama 3.3 70B Q4 |
| ~$20,000 rack | 96–192 GB | ~100–235B MoE @ 4-bit | GLM-4.5-Air 106B, Llama 4 Scout 109B |
| **Flagship 400B–1T MoE** | 8× H100 (640 GB) | GLM-5.2, DeepSeek V4, Mistral Large 3, Llama 4 Maverick | **~$40k/mo AWS / six-figure on-prem** |

**Capability.** A self-hostable *small* model (7–70B on a $1–5k budget) is below
the floor for the hard tail above. The strong open models people reach for —
GLM-5.2 (~744B MoE), DeepSeek V4 (~1T MoE), Mistral Large 3 (675B), Llama 4
Maverick (400B) — are **flagship MoEs that need a $40k/month, 8×H100-class box to
self-host**. But every one of those is available **managed on Bedrock, per-token,
for cents** — so "we want a strong open model" argues for **managed**, not a rack.

Self-hosting only makes sense for a small model at **very high sustained volume**,
or a hard requirement (full data control, air-gapped / Switzerland-only) — both
accepting the capability floor and the ops burden.

## Keeping the cost down

Cost is driven by input tokens, so the standard, publicly-documented
Bedrock/Anthropic levers apply — no bespoke engineering needed to start:

- **Prompt caching** — cache reads cost a fraction of fresh input; on a workload
  that repeats a large prefix every call, this is the highest-value lever.
- **Right-size the model per turn** — send simpler turns to a smaller, cheaper
  model and reserve the capable model for the hard ones (see
  [Do we need a large model?](#do-we-need-a-large-model)).
- **Batch API (50% off)** — for offline / non-interactive jobs only; not for
  interactive chat.

Beyond these, further prompt- and tool-engineering can reduce token use; those are
tuned during implementation against measured traces.

## Data residency

The app is deployed in **Europe (Frankfurt), `eu-central-1`**. Claude is not hosted
*in-region* in Frankfurt or Zurich; it is reached through the Amazon Bedrock **EU
cross-region inference profile** (`eu.anthropic.claude-*`), which keeps every request
within EU regions — data stays in the EU, and Bedrock retains no prompts or outputs
by default. This gives EU residency without the burden of self-hosting.

EU inference profiles exist today for **Opus 4.x, Sonnet 4.x, and Haiku 4.5**; the
newest models may ship global-only first (e.g. Sonnet 5). If EU-only routing is a
hard requirement, model choice is limited to what has an `eu.` profile at the time,
and that regional profile adds ~10% over the global endpoint.

**Zurich (`eu-central-2`)** is the intended region for the production compute/data
path if in-country Swiss residency is needed; it is an opt-in region that must be
enabled on the account first, and Claude would still be reached through the EU
inference profile regardless. See [`deployment.md`](../deployment.md#region-note).

## Recommendation

Start on **Claude via Bedrock (EU profile)** to set a quality ceiling and build an
eval set of real Swiss-geodata questions (all five languages). Then work down the
cost curve, gating each step on the same eval:

1. **Claude, single tier** — the current design; establishes quality and the eval.
2. **Add model tiering** — route simple turns to Haiku (or a small open model),
   keep the complex tail on Sonnet/Opus. Biggest saving, no infra change.
3. **Managed open model** — change the model ID to a strong open-weight; measure
   the quality gap and the ~10× saving. (Config change only.)
4. **EC2 self-host** — only if very high volume or a hard data-control requirement
   justifies the fixed cost and ops. (New infrastructure.)

Apply the standard [cost levers](#keeping-the-cost-down) throughout. Model and
hosting choice is largely a config swap (Bedrock `InvokeModel` + inference
profile), so none of this locks us in.

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
- EU inference-profile availability and Frankfurt (`eu-central-1`) GPU rates
  cross-checked against the live AWS APIs, 2026-07.
