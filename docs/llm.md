# LLM

LLM provisioning and model choice for the agent backend are described in this document. More detail and decisions will follow
during project execution.

## Access

Claude and Mistral models are reached through **Amazon Bedrock** using **EU
inference profiles** (`eu.*`), so inference stays within EU regions; the backend
authenticates with its task IAM role (no API key). See
[`deployment.md`](./deployment.md#backend-deployment) and
[`architecture.md`](./architecture.md#backend-architecture).

## Initial models

The pilot starts with two models, plus a third pending release:

- **Claude Sonnet 4.6** — Bedrock model ID `eu.anthropic.claude-sonnet-4-6`,
  confirmed with swisstopo on 2026-07-20. The primary agent model: strong at
  the tool use and multilingual reasoning this backend depends on, and
  **GOV.UK Chat runs this exact stack — Claude on Bedrock — at national
  scale**.
- **Mistral** — the second provider, also served from Bedrock EU regions. Gives
  us a European model to evaluate side by side on the same harness; the exact
  variant is fixed during evaluation.
- **Apertus** *(possibly)* — the Swiss open-weights model from the Swiss AI
  Initiative (ETH Zürich / EPFL). Joins the lineup if the new version is
  released in time for the pilot; attractive for Swiss data sovereignty and
  for the national languages, including Romansh, which the UI already ships.

Other Claude tiers (**Opus 4.8** for escalation, **Haiku 4.5** for routing
simple turns) remain available on the same EU profile if evaluation shows the
need. **Sonnet 5** has no `eu.` inference profile yet; an upgrade within the
Claude family is low-effort once one ships.

## Cost & alternatives

The cost analysis and the full model comparison (managed vs open vs
self-hosted, and the staged rollout plan) are part of the WP3 report, which is
handed in separately and not tracked in this repository.
