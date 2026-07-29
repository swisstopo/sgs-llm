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
- **Apertus 1.5** — released 2026-07-24 by the Swiss AI Initiative (ETH Zürich /
  EPFL / CSCS). Attractive for Swiss data sovereignty and for the national
  languages, including Romansh, which the UI already ships. **Not deployable on
  Bedrock**, so it is evaluated offline for the pilot rather than wired into the
  deployed backend — see [Apertus 1.5](#apertus-15).

Other Claude tiers (**Opus 4.8** for escalation, **Haiku 4.5** for routing
simple turns) remain available on the same EU profile if evaluation shows the
need. An upgrade within the Claude family is low-effort: the model id is a task
definition environment variable (`BEDROCK_PRIMARY_MODEL_ID`), not a code or image
change. Resolve the ids that actually exist in the account before deploying:

```bash
aws bedrock list-inference-profiles --profile swisstopo --region eu-central-1 \
  --type SYSTEM_DEFINED --query 'inferenceProfileSummaries[].inferenceProfileId'
```

## Apertus 1.5

Released **2026-07-24** in 8B and 70B sizes (Apache 2.0), now multimodal, with a
262k context and training aimed at tool use — the capability this backend depends
on. Two findings decide how it can be used:

- **Bedrock cannot host it.** Bedrock Custom Model Import supports only the
  Mistral, Mixtral, Flan, Llama (2/3.x/Mllama), GPTBigCode, Qwen2/2.5/3 and
  GPT-OSS architectures. Apertus 1.5 is `ApertusForMultimodalLM` with the xIELU
  activation, and it is not in the Bedrock catalogue or Bedrock Marketplace. So
  unlike Claude and Mistral it cannot be reached through an EU inference profile.
- **Self-hosting is straightforward but not free.** vLLM serves it with an
  OpenAI-compatible API and a native Apertus tool-call parser
  (`--enable-auto-tool-choice --tool-call-parser apertus`), which would drop in
  next to Bedrock. The 70B needs 4 GPUs (`--tensor-parallel-size 4`, e.g.
  `g6e.12xlarge`); the 8B fits a single L40S but is unlikely to hold up on agentic
  tool use.

**Decision for the pilot: evaluate Apertus offline; do not deploy it.** The
deployed backend ships with Bedrock Claude + Mistral, and Apertus is compared on
answer quality separately, so no GPU capacity or 24/7 endpoint cost is carried
during the pilot. The options if that changes, roughly in order of effort:

| Option | Trade-off |
| --- | --- |
| **EC2 `g6e` + vLLM**, started per evaluation window | OpenAI-compatible with native tool calling, cheapest per GPU-hour, mirrors the existing EC2 pattern. Watch for `InsufficientInstanceCapacity` on g6e in eu-central-1 |
| **SageMaker real-time endpoint** (vLLM/LMI) | Managed and IAM-native in-region, but the invoke API is not OpenAI-shaped (needs an adapter) and it is the most expensive if left running |
| **Public AI hosted API** (`platform.publicai.co`) | Zero GPU ops, available today — but a third-party endpoint outside AWS, so prompts leave the account |
| **Swisscom sovereign Swiss AI platform** | Apertus hosted **in Switzerland** — the strongest residency story and the natural production path; needs a commercial agreement |
| **Bedrock Marketplace / SageMaker JumpStart** | Not listed today; zero effort if it ever appears — worth re-checking at evaluation time |

Because the backend reaches Bedrock through one model abstraction, keeping that
layer able to take an **OpenAI-compatible base URL** is what preserves every
option above at no cost today.

## Developer access

Trying prompts and comparing models does not need the deployed backend: the
`sgs-llm-dev` IAM role grants Bedrock inference on the pilot's EU profiles (plus
read-only access to the stored feedback and conversation tables) from a fixed
network address, with no long-lived key. Setup and examples are in
[`deployment.md`](./deployment.md#use-the-models-from-a-workstation).

## Cost & alternatives

The cost analysis and the full model comparison (managed vs open vs
self-hosted, and the staged rollout plan) are part of the WP3 report, which is
handed in separately and not tracked in this repository.
