# LLM

LLM provisioning and model choice for the agent backend are described in this document. More detail and decisions will follow
during project execution.

## Access

Claude is reached through **Amazon Bedrock** using an **EU cross-region
inference profile** (`eu.anthropic.claude-*`), so inference stays within EU
regions; the backend authenticates with its task IAM role (no API key). See
[`deployment.md`](./deployment.md#backend-deployment) and
[`architecture.md`](./architecture.md#backend-architecture).

## Initial model

We use **Claude Sonnet 4.6** — Bedrock model ID
`eu.anthropic.claude-sonnet-4-6`. This is the recommendation of
[`WP3_Report.md`](./WP3_Report.md) (§1, §7.1), confirmed with swisstopo on
2026-07-20.

Sonnet 4.6 is the mid tier that clears the agentic bar without frontier pricing:
it is strong at the tool-use and multilingual reasoning this backend depends on,
**GOV.UK Chat runs this exact stack — Claude on Bedrock — at national scale**,
and the managed Bedrock EU endpoint removes the operational burden of
self-hosting. **Opus 4.8** remains available on the same EU profile if evaluation
shows Sonnet missing a hard tail, and **Haiku 4.5** is the routing tier for
simple turns.

**On Sonnet 5:** benchmarks better and its list price looks lower ($2/$10 vs
$3/$15), but two things blunt that. It has **no `eu.` inference profile yet**, and
the $2/$10 is introductory pricing that lapses 2026-08-31. And Sonnet 5 uses a
**newer tokenizer that emits ~30% more tokens** for the same text, which largely
cancels the lower per-token rate — so expect rough cost parity with 4.6 by the
time we deploy, not a saving. An upgrade within the Claude family is low-effort; a
cross-family swap is not (see
[`model-cost-options/cost-model.md`](./model-cost-options/cost-model.md) §7).

## Cost & alternatives

Cost estimates for Claude vs open vs self-hosted models, whether the task needs a
large model, and a staged test plan for the alternatives are in
[`model-cost-options/cost-model.md`](./model-cost-options/cost-model.md).
