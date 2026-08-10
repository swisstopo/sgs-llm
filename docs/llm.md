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
  us a European model to evaluate side by side on the same harness. The variant
  was fixed during evaluation to **`mistral.ministral-3-14b-instruct`**, called
  in-region in `eu-west-1` — see [the evaluation evidence](#workaround-found-for-mistral-in-region-on-demand-in-eu-west-1).
- **Apertus 1.5** — released 2026-07-24 by the Swiss AI Initiative (ETH Zürich /
  EPFL / CSCS). Attractive for Swiss data sovereignty and for the national
  languages, including Romansh, which the UI already ships. **Not deployable on
  Bedrock**, so it is evaluated offline for the pilot rather than wired into the
  deployed backend — see [Apertus 1.5](#apertus-15).

Other Claude tiers (**Opus 4.8** for escalation, **Haiku 4.5** for routing
simple turns) remain available on the same EU profile if evaluation shows the
need. An upgrade within the Claude family is low-effort: the model id is a task
definition environment variable (`BEDROCK_PRIMARY_MODEL_ID`), not a code or image
change.

## Availability in the POC account (verified 2026-07-29, eu-central-1)

```bash
aws bedrock list-inference-profiles --profile swisstopo --region eu-central-1 \
  --type SYSTEM_DEFINED --query 'inferenceProfileSummaries[].inferenceProfileId'
```

**EU inference profiles that exist** include `eu.anthropic.claude-sonnet-4-6`,
`eu.anthropic.claude-sonnet-5`, `eu.anthropic.claude-opus-4-8`,
`eu.anthropic.claude-opus-5`, `eu.anthropic.claude-haiku-4-5-20251001-v1:0` and
`eu.mistral.pixtral-large-2502-v1:0`. Note that **Sonnet 5 now does have an `eu.`
profile** — the earlier note that it did not is out of date. Whether to move the
pilot from Sonnet 4.6 to Sonnet 5 is a swisstopo decision, not a technical one:
it is one environment variable.

**Mistral is thinner than expected in this region.** Only two Mistral models are
offered in eu-central-1 at all:

| Model | Inference type | Notes |
| --- | --- | --- |
| `mistral.pixtral-large-2502-v1:0` | EU inference profile only | 124B multimodal, general-purpose — the intended evaluation model |
| `mistral.devstral-2-123b` | **ON_DEMAND, in-region** | Verified working; but Devstral is Mistral's coding/agentic-software model, not the general multilingual model this use case wants |

**Mistral Large 3 and the Ministral 3 family are not available in eu-central-1**,
despite being on Bedrock elsewhere. So "Mistral on Bedrock in the EU" means Pixtral
Large, or a different region.

### ✅ Resolved (2026-07-30): an organization SCP denied cross-region inference

> **Status.** swisstopo IT amended SCP `p-ddxnpgbm` on **30 July
> 2026** — "the region should be available now". The deny below is gone: the next
> call got past it and failed differently, on the Anthropic use-case form
> ([next section](#-blocker-anthropic-use-case-details-form-not-submitted)). The
> diagnosis is kept because it explains why the deployment is shaped the way it
> is, and what to look at if the guardrail is ever reinstated.

As first observed on 2026-07-29, every `eu.*` profile failed, for **Claude and
Mistral alike**:

```text
AccessDeniedException: not authorized to perform: bedrock:InvokeModel on resource:
arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-sonnet-4-6
with an explicit deny in a service control policy:
arn:aws:organizations::705927066274:policy/o-ysrrabz20z/service_control_policy/p-ddxnpgbm
```

The cause was structural, not a misconfiguration of this project: an EU inference
profile **routes the request to another EU region** (observed: `eu-north-1` for
Claude, `eu-west-3` for Nova), and an organization-level SCP denied Bedrock
actions in those regions. Consequences at the time:

- **Bedrock itself works in eu-central-1.** In-region on-demand calls succeed —
  `mistral.devstral-2-123b` and `qwen.qwen3-235b-a22b-2507-v1:0` were both invoked
  successfully.
- **No IAM change in this project could fix it.** An SCP deny overrides any
  identity-based Allow, including for an account administrator — which is why this
  had to be resolved by the management account, not here. The task role and
  developer role were already correct and needed no change when the SCP was
  amended.
- **The models the pilot wants are all EU-profile-only in this region** (recent
  Claude is not hosted in-region in Frankfurt, and neither is Pixtral Large), so
  they were unreachable for as long as the deny stood.
- **Restart the service whenever such a gate lifts.** The backend marks a denied model
  unavailable for the lifetime of the process, so it stops paying the failed call on
  every turn. Running tasks therefore keep serving from the secondary until they are
  replaced: `aws ecs update-service --cluster sgs-llm --service sgs-llm-backend
  --force-new-deployment`. Nothing else needs changing.

#### Workaround found for Mistral: in-region on-demand in eu-west-1

The SCP is **region-scoped, and eu-west-1 (Ireland) is permitted**. Probing every
EU region for models callable *in-region* (no cross-region profile, therefore no
SCP problem) found a usable Mistral there:

| Region | anthropic / mistral available ON_DEMAND in-region | SCP |
| --- | --- | --- |
| `eu-central-1` | `mistral.devstral-2-123b`, `anthropic.claude-3-haiku` | allowed |
| `eu-west-1` | Ministral 3 (3B/8B/14B), `mistral.mistral-large-2402`, `magistral-small-2509`, Voxtral, Devstral 2, Mixtral | allowed |
| `eu-west-2`, `eu-west-3`, `eu-north-1` | — | **API call denied** |
| `eu-south-1`, `eu-south-2`, `eu-central-2` | — | region not enabled |

**`mistral.ministral-3-14b-instruct` in `eu-west-1` is the pilot's secondary
model.** It was chosen on evidence rather than the datasheet: given the project's
own demo query and a geodata tool definition, it returned
`stopReason: tool_use`, calling `find_geodata_layer` with
`{"canton": "Wallis", "query": "Hochwassergefahren"}` — correct tool selection and
correct German-to-arguments extraction, which is exactly what the agent loop
needs. `magistral-small-2509` answered the same prompt with `end_turn` and no tool
call, so it was rejected; `mistral.mistral-large-2402` is older and returned no
usable content.

Because the two models live in different regions, the task definition carries
`BEDROCK_SECONDARY_REGION` (`eu-west-1`) alongside `BEDROCK_REGION`
(`eu-central-1`). Ireland is inside the EU, and an in-region on-demand call does
not leave it, so this is a *better* residency story than cross-region inference,
not a worse one.

**Claude had no such workaround**, which is why the SCP had to be amended rather
than worked around. Recent Claude is not hosted in-region in any EU region —
eu-central-1 offers only Claude 3 Haiku, eu-west-1 only Claude 3 Sonnet/Haiku.
Anything from Sonnet 4.6 upward is EU-profile-only, so it stayed unreachable until
the guardrail changed.

**Resolution (2026-07-30).** An administrator of the management account
(`705927066274`) amended SCP `p-ddxnpgbm` to permit `bedrock:InvokeModel` /
`bedrock:InvokeModelWithResponseStream` in the regions the EU profiles route to.
Inference still stays inside the EU — that is the same region set the EU profile
is designed around. No configuration had to change: the roles were already correct.
Only the running tasks needed replacing (the restart note above) so a fresh process
would retry Claude.
Re-confirm the routed regions at any time with `aws bedrock get-inference-profile
--inference-profile-identifier eu.anthropic.claude-sonnet-4-6`.

### ⚠️ Blocker: Anthropic use-case details form not submitted

With the SCP amended, the first Claude call reached Anthropic's own gate instead:

```text
ResourceNotFoundException: {
  "message": "Model use case details have not been submitted for this account.
   Fill out the Anthropic use case details form before using the model.
   If you have already filled out the form, try again in 15 minutes."
}
```

Bedrock requires a one-time [use-case submission per account][anthropic-access]
before Anthropic models can be invoked — an account-level form, not an IAM or SCP
matter, so again nothing in this project can fix it. The form text was agreed with
swisstopo on 2026-07-31 (conversational assistant for public Swiss federal
geodata; users are members of the public plus swisstopo staff). **Submission is
with askEarth**, falling back to swisstopo IT if the rights are missing. Access
propagates within ~15 minutes of submission.

[anthropic-access]: https://repost.aws/knowledge-center/bedrock-access-anthropic-model

**Current state of the deployed backend:** primary
`eu.anthropic.claude-sonnet-4-6` (**pending the use-case form**), secondary
`mistral.ministral-3-14b-instruct` in `eu-west-1` (**working**). Claude starts
working once the form clears **and the service is restarted** — this failure is a
`ResourceNotFoundException`, which the backend also caches for the life of the
process (restart note above). No configuration change is needed.

Note that the secondary model stays on merit, not as a fallback: an in-region
on-demand call in Ireland never leaves the EU, which is a *better* residency story
than cross-region inference, and it was the variant that actually produced correct
tool calls. What the amended SCP reopens is **Pixtral Large** — the intended
general-purpose multimodal evaluation model, EU-profile-only and therefore untested
until now — as a candidate worth re-probing.

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
