# Model & hosting cost — SGS LLM

A short cost comparison for the agent backend's language model: **Claude on
Bedrock**, an **open model on Bedrock**, and a **self-hosted small model**. It
answers four questions — what Claude costs, what an open model costs, whether we
need a large model, and whether a self-hosted small model would be enough.

All figures are **public USD list prices** (mid-2026), for illustration. Confirm
the exact rate for the pinned model and region in the AWS console before quoting a
budget.

## What one question costs, in tokens

The backend runs a **stateless agentic loop**: every turn re-sends the full
conversation history, the map context, the system prompt, and the tool schemas,
and the model may call tools a few times before it answers. So one user question
is several model calls with growing input.

Planning figure: **~40,000 input + ~2,000 output tokens per answered question**
(≈3 model calls). This is an engineering estimate — replace it with logged token
counts once the backend runs on Bedrock. Only the numbers change, not the method.

## The four questions, answered

1. **What does Claude via Bedrock cost?** ~**$50–275 per 1,000 questions**
   depending on tier (Haiku → Opus, including the EU +10% below), and roughly
   halved again with prompt caching. At pilot volume that is a few hundred
   $/month.
2. **What would an open model cost?** ~**$8–140 per 1,000 questions**. A capable
   open model (Llama 4) is **~10–30× cheaper** than Opus-class Claude, on the same
   API and same EU profile.
3. **Do we really need a large model?** Decide with an **eval**, not a guess. The
   task is agentic multi-step tool use, multilingual including **Romansh**, over
   official geodata — the hard case for small models. And at pilot volume token
   cost is small, so answer quality should drive the choice.
4. **Would a self-hosted small model be enough?** Maybe on capability (the eval
   decides), but **not automatically cheaper**: a GPU is a fixed **~$1,000–1,700
   /month + ops**, so a managed open model on Bedrock wins below ~100k questions
   /month.

## 1. Claude via Bedrock

Per-1M list price (Bedrock matches the Anthropic API), and the cost for 1,000
questions at the estimate above:

| Model | Input /1M | Output /1M | ~Per 1,000 questions |
| --- | --- | --- | --- |
| Opus 4.8 (frontier) | $5 | $25 | ~$250 |
| Sonnet 4.6 (mid) | $3 | $15 | ~$150 |
| Haiku 4.5 (small) | $1 | $5 | ~$50 |

- **EU data residency: +~10%.** The EU-confined `eu.` endpoint we use is a
  regional endpoint, which for Claude 4.5+ costs ~10% more than global. Real
  figures ≈ **$275 / $165 / $55** per 1,000 questions.
- **Prompt caching cuts input ~90%.** A cache read costs 0.1× the input price.
  Because the loop repeats the system prompt, tool schemas, and history on every
  call, most input becomes a cache read.
- **Sonnet 5** is cheaper right now ($2/$10 introductory to 2026-08-31) but is
  **global-only on Bedrock today** — not usable under EU-only routing yet.

## 2. Open model via Bedrock

Same Bedrock API and same EU profile — only the model ID changes:

| Model | ~Per 1,000 questions |
| --- | --- |
| Llama 4 Scout | ~$8 |
| Mistral Small | ~$9 |
| Llama 4 Maverick | ~$12 |
| Mistral Large 2 | ~$138 (≈ Sonnet) |

## 3. Self-hosted small model (EC2 GPU)

Self-hosting swaps per-token cost for a **fixed monthly GPU bill** — the same
whether the app is busy or idle. Real Frankfurt on-demand rates:

| Instance | GPU | Fits | 24×7 /month | 1-yr commit |
| --- | --- | --- | --- | --- |
| g5.xlarge | A10G 24 GB | 7–8B model | ~$918 | ~$550 |
| g6e.xlarge | L40S 48 GB | ≤~30B (quantized) | ~$1,699 | ~$1,020 |

Not in the sticker price: serving, scaling, patching, model updates, monitoring,
on-call — recurring engineering time.

**Break-even vs a managed open model on Bedrock (~$12/1,000 q):** about
**85,000–140,000 questions/month** before self-hosting is even on price — and that
ignores the ops load. Below that, the managed open model is cheaper *and*
zero-ops. Self-hosting earns its keep at high sustained volume, or when a
requirement (full data control, Switzerland-only deployment, a fine-tuned model)
makes it non-negotiable.

## Data residency

The backend reaches the model through an **EU-confined inference profile**
(`eu.anthropic.*`): requests route only within EU regions, and prompts/outputs are
held in memory, not stored. This keeps processing in the EU without the burden of
self-hosting. EU-confined profiles exist today for **Opus 4.x, Sonnet 4.x, and
Haiku 4.5**; the newest models may ship global-only first (e.g. Sonnet 5). If
EU-only routing is a hard requirement, model choice is limited to what has an
`eu.` profile at the time, and that profile adds ~10% over global.

## Recommendation

Start on **Claude via Bedrock (EU profile)** to set a quality ceiling and build an
eval set of real Swiss-geodata questions (all five languages). Then run the same
eval on cheaper options and stop at the cheapest that still passes:

1. **Claude via Bedrock** — the current design; establishes quality and the eval
   set.
2. **Open model via Bedrock** — change the model ID; measure the quality gap and
   the ~10–30× saving. (Config change only.)
3. **Self-hosted small model** — one GPU + vLLM/TGI; do this last, only if steps
   1–2 justify it. (New infrastructure.)

Model choice is a config swap (Bedrock `InvokeModel` + inference profile), so none
of this locks us in.

## Sources

- [Anthropic model pricing](https://platform.claude.com/docs/en/about-claude/pricing)
  — per-model prices, prompt-caching multipliers, regional +10%, batch discount
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)
- [Cross-region inference for EU data processing (AWS Switzerland blog)](https://aws.amazon.com/blogs/alps/unlocking-ai-flexibility-in-switzerland-a-guide-to-cross-region-inference-for-eu-data-processing-and-model-access/)
- [Amazon EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/) ·
  [EC2 G6e](https://aws.amazon.com/ec2/instance-types/g6e/) ·
  [EC2 G5](https://aws.amazon.com/ec2/instance-types/g5/)
- EU inference-profile availability and Frankfurt GPU rates cross-checked against
  the live AWS APIs, 2026-07.
