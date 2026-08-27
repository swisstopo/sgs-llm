# Apertus 1.5 on AWS — deployment notes

**Deployed.** The stack `sgs-llm-apertus` runs in `eu-central-1` on a weekday
office-hours schedule. [`docs/apertus-endpoint.md`](../../docs/apertus-endpoint.md)
is the operational card — addresses, schedule, manual override, capacity risk.
This file is the investigation behind it: what was measured, where the official
guide is wrong, and the licensing position.

The findings below were verified live on 2026-08-25 against the AWS APIs, the
HuggingFace API and ghcr.io, in `eu-central-1` (Frankfurt), while the work was
still read-only and no resources existed yet. That is why some figures here are
quoted on an A10G: the stack ultimately deployed on an L4, and the endpoint card
carries the numbers that actually apply to the running system.

---

## The HuggingFace token: resolved

**There is no HuggingFace token in this account.** The deployed stack mirrors the
model weights to a private S3 bucket in-region and serves them from local disk,
with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` set so nothing can reach
huggingface.co. `/apertus/hf-token` has been deleted; only `/apertus/api-key`
remains. Verified across a full stop/start with the token absent.

This retired the four separate problems the exploration token had - that it was
personal rather than a service account, that it was over-scoped, that it lived
where a `.env` could leak it, and that it had been pasted into a chat transcript.
None of them apply to a token that does not exist.

**The exploration token should still be revoked at
<https://huggingface.co/settings/tokens>.** Deleting it from SSM removed AWS's
copy; only HuggingFace can invalidate the credential itself.

**A brand-new setup still needs a token once**, to populate an empty mirror. The
step-by-step is in `docs/apertus-endpoint.md`; the short version is deploy with
`WeightsS3Uri=''`, let the instance pull from HuggingFace, seed the bucket from
it, set `WeightsS3Uri`, then delete the token for good.

Two things about that first-time token that are easy to get wrong:

- **Gate acceptance is per HF account, not per token.** A fresh token with
  `canReadGatedRepos: true` is still refused until *that account* has clicked
  "Agree and access repository". Verified during this work.
- Accepting the gate accepts the Apertus **Acceptable Use Policy** on swisstopo's
  behalf, so it should be someone entitled to do that.

---

## TL;DR

| Question | Answer |
|---|---|
| Can we run the 8B at 4K context? | Yes — it is, on `g6.2xlarge` (L4 24 GB) with 4 concurrent sequences. A 24 GB card is enough; the `g6e.xlarge` (L40S 48 GB) sizing below was cautious. |
| Cost, always-on, 1× 8B instance | **$754–$1,718/mo** on-demand; **$356–$753/mo** on a 3-yr RI. |
| Cost, always-on, 70B | **$9,625/mo** on-demand (`g6e.12xlarge`); **$4,185/mo** on a 3-yr RI. |
| Throughput, 8B | ~27–39 tok/s single stream; ~300–470 tok/s aggregate at batch 32. |
| Throughput, 70B | ~11 tok/s single stream on L40S ×4; ~53 tok/s on A100 ×8. |
| Is the hardware available? | Quota yes; capacity varies. At deployment, G5 and G6e returned `InsufficientInstanceCapacity` in all three `eu-central-1` AZs. G6 (L4) had capacity and is what runs. |
| NVIDIA licensing | Clean. No extra licence, no extra cost. See below. |
| Blockers | HF gate resolved. Remaining: v1.5 needs the Swiss AI vLLM image, not upstream. |

---

## Blockers

**1. ~~The v1.5 repos are gated.~~ RESOLVED — gate accepted 2026-08-25.**

The v1.5 repos are gated (`gated: auto`). The gate has since been accepted and
both configs now read successfully, which is how the architecture facts below
were confirmed rather than inferred.

Kept here because it recurs: any *new* HF token, or any other account that needs
to pull these weights, must accept the gate separately at
<https://huggingface.co/swiss-ai/Apertus-v1.5-8B> and
<https://huggingface.co/swiss-ai/Apertus-v1.5-70B>. A token with
`canReadGatedRepos: true` is **not** sufficient on its own — the underlying
account must be on the authorised list. That includes CI and any automated
pull on a fresh instance.

Accepting binds you to the Apache 2.0 licence **and** the Apertus 1.5 Acceptable
Use Policy, and shares your contact details with the Swiss AI Initiative. The AUP
is a real, separate obligation — the repo ships `USAGE_POLICY.pdf`,
`Apertus_1_5_EU_Code_of_Practice.pdf` and `Apertus_1_5_EU_Public_Summary.pdf`.
Worth a read before this goes anywhere near production.

**2. Upstream vLLM cannot load Apertus 1.5.** *(confirmed against the real config)*

With gate access granted, the v1.5 `config.json` declares:

```json
"architectures": ["Apertus1p5ForConditionalGeneration"],
"model_type": "apertus1p5"
```

vLLM's model registry on `main` contains exactly one Apertus entry:

```python
"ApertusForCausalLM": ("apertus", "ApertusForCausalLM"),
```

Different class, different `model_type`. There is no `apertus_mm.py` in upstream
(404). So `vllm serve swiss-ai/Apertus-v1.5-8B` on a stock `pip install vllm` will
fail at load with an unsupported-architecture error — this is not a version-skew
guess, the names simply do not match. Swiss AI say outright that "upstreaming is
in progress".

So for v1.5 you must use their published image, which does exist and is publicly
pullable (verified: 21 layers, 8.9 GB compressed):

```
ghcr.io/swiss-ai/vllm_apertus_1.5_release:latest-amd64
ghcr.io/swiss-ai/vllm_apertus_1.5_release:latest-arm64
```

Tags available: `latest`, `latest-amd64`, `latest-arm64`, `pr-190*`. All are
`latest`-style on a fork with no release cadence, so the stack pins by digest
instead:

```
ghcr.io/swiss-ai/vllm_apertus_1.5_release@sha256:6faeeeeeb7960440d42139bce55ad68ecbf0b538edfb205dec96ea4ce69d4a6b
```

Inspecting that image's config surfaced two things that affect how it is run:

- **Entrypoint is `/opt/nvidia/nvidia_entrypoint.sh` with no `CMD`.** Unlike
  `vllm/vllm-openai`, bare flags are not appended to a server invocation — they
  would be exec'd as a binary. The full `vllm serve <model> ...` command must be
  passed. vLLM runs from a source checkout at `/workspace/vllm`, not a wheel.
- **CUDA 13.0, and its `NVIDIA_REQUIRE_CUDA` guard only accepts driver branches
  535 / 550 / 565 / 570 / 575.** A host on driver 580+ is newer and perfectly
  capable, but the guard does not know that and will abort the container. Check
  `nvidia-smi` on the instance; if the branch is outside that list, set
  `NVIDIA_DISABLE_REQUIRE=1` (commented into the compose file) or pin a DLAMI
  with a 570/575 driver. **This is the most likely first-run failure.**

`TORCH_CUDA_ARCH_LIST` is `7.5 8.0 8.6 8.9 9.0 10.0 11.0 12.0+PTX`, which covers
every GPU considered here — A10G (8.6), L4/L40S (8.9), A100 (8.0), H100 (9.0).

---

## Corrections to the official guide

The [guide's](https://www.apertus-ai.org/docs/guides/vllm/) `docker-compose.yml`
does not work as written. The stack's boot script incorporates the fixes; what
was wrong:

| Issue | Reality |
|---|---|
| `image: ghcr.io/vllm/vllm:nightly` | Not a published image. Upstream is `vllm/vllm-openai`. |
| `HF_MODEL` / `MAX_MODEL_LEN` env vars | vLLM reads neither. Model and context length are **command arguments**. |
| No GPU reservation | Container starts on CPU, then fails. Needs `deploy.resources.reservations.devices`. |
| `nginx.conf` mounted into the vLLM container | Meaningless there. |
| `depends_on: nginx` on the vLLM service | Backwards — the proxy depends on the backend. |
| nginx service with no config | Nothing is proxied. Also needs `proxy_buffering off` or SSE streaming breaks. |
| No `ipc: host` | vLLM needs a large `/dev/shm`. |

**And one that will bite hardest:** the model card's `--gpu-memory-utilization 0.6`
is calibrated for an 80 GB H100. Applied to a 24 GB card it yields a 13.4 GiB
budget against 17.1 GiB of v1.5 weights — the server will not start.

| GPU | VRAM | 0.6 budget | v1.5 8B weights | verdict |
|---|---|---|---|---|
| A10G (g5) | 22.4 GiB | 13.4 GiB | 17.1 GiB | **OOM — weights alone exceed it** |
| L4 (g6) | 22.4 GiB | 13.4 GiB | 17.1 GiB | **OOM — weights alone exceed it** |
| L40S (g6e) | 44.7 GiB | 26.8 GiB | 17.1 GiB | OK |

On 24 GB cards raise it to ~0.92. The compose file uses 0.90 on L40S.

---

## The HuggingFace "Use this model" snippet

The HF model page shows an auto-generated vLLM/Docker snippet. It is template
boilerplate rendered from repo tags, not written by Swiss AI, and **most of it
does not work for this model**.

| Snippet line | Verdict |
|---|---|
| `hf auth login` | Fine. Equivalent to setting `HF_TOKEN`; needed either way for a gated repo. |
| `pip install vllm` + `vllm serve swiss-ai/Apertus-v1.5-8B` | **Fails.** Stock vLLM has no `Apertus1p5ForConditionalGeneration`. Use the Swiss AI image. |
| `curl` with `image_url` content parts | **Correct and useful.** Standard OpenAI vision format, which vLLM implements. |
| `docker model run hf.co/swiss-ai/Apertus-v1.5-8B` | **Fails.** Docker Model Runner needs GGUF; the repo ships safetensors only. |

On that last one: two community GGUF conversions exist
(`andreasmartin/apertus-v1.5-8b-text-Q8_0-GGUF`,
`katya228/Apertus-v1.5-70B-text-GGUF`) but note the `-text-` in both names — they
are text-only conversions that discard the vision and audio tokenizers, i.e. the
whole reason to run 1.5 over 1.0. They are also third-party, unaffiliated with
Swiss AI, and not something to put in front of production traffic.

The snippet contradicts Swiss AI's own model card, which says upstreaming is still
in progress and points at their image. Trust the card, not the widget.

---

## Model facts (from the published configs)

Read from the actual `config.json` of each repo (v1.5 values confirmed after the
gate was accepted, not inferred).

| | 8B v1.0 | 8B v1.5 | 70B v1.5 |
|---|---|---|---|
| HF id | `Apertus-8B-Instruct-2509` | `Apertus-v1.5-8B` | `Apertus-v1.5-70B` |
| Architecture class | `ApertusForCausalLM` | `Apertus1p5ForConditionalGeneration` | `Apertus1p5ForConditionalGeneration` |
| `model_type` | `apertus` | `apertus1p5` | `apertus1p5` |
| Params | 8.05 B | 8.90 B | 72.0 B |
| Weights (bf16) | 16.1 GB | 18.4 GB | 144.6 GB |
| Hidden / layers / heads / KV heads | 4096 / 32 / 32 / 8 | 4096 / 32 / 32 / 8 | 8192 / 80 / 64 / 8 |
| Head dim | 128 | 128 | 128 |
| KV cache | 128 KiB/token | 128 KiB/token | 320 KiB/token |
| Vocab | 131 072 | 266 752 | 266 752 |
| Max context | 65 536 | 262 144 | 262 144 |
| Gated | no | yes (auto) — **accepted** | yes (auto) — **accepted** |
| Multimodal | no | image + experimental audio | image + experimental audio |
| Stock vLLM | **yes** | no — fork | no — fork |
| Licence | Apache 2.0 | Apache 2.0 + AUP | Apache 2.0 + AUP |

The v1.5 config nests the language model under `text_config` (`model_type:
apertus1p5_text`) alongside `vision_tokenizer_config` and `audio_tokenizer_config`
(a `WavTokenizerModel`), with `image_token_id` 131084 / `audio_token_id` 131085.
The enlarged 266 752 vocab is the text vocab padded out for image and audio tokens.

The layer and KV-head counts above confirm the KV-cache figures used in the cost
model — 128 KiB/token for the 8B and 320 KiB/token for the 70B were derived from
the v1.0 configs before the gate opened, and the real v1.5 configs match.

Activation is `xielu` in all cases — a non-standard activation, which is why
the architecture needs explicit support rather than loading as a Llama variant.

---

## AWS capacity and quotas

`eu-central-1`, all three AZs, *offer* `g5`, `g6`, `g6e` and `p4d`. `p5` (H100) is
**not** offered in Frankfurt — nearest are `eu-north-1`, `us-east-1`, `us-west-2`.

**Offered is not the same as available, and this bit us.** At deployment time
`g5.xlarge`, `g5.2xlarge`, `g5.4xlarge` and `g6e.xlarge` all returned
`InsufficientInstanceCapacity` in every `eu-central-1` AZ over roughly an hour.
`g6` (L4) was the only family with capacity, which is why the stack runs on
`g6.2xlarge`. Quota was never the constraint — the numbers below were all in
place. Plan for a launch to fail and retry, not for a family to be there on
demand.

Quotas on account `259789526488`:

| Region | On-demand G&VT vCPU | On-demand P vCPU | Spot G&VT | Spot P |
|---|---|---|---|---|
| eu-central-1 | **384** | **384** | **0** | 384 |
| us-east-1 | 384 | 384 | **0** | 384 |
| eu-north-1 | **0** | **0** | 0 | 0 |

- 384 G vCPU is ample: `g6e.xlarge` is 4 vCPU, `g6e.12xlarge` is 48.
- 384 P vCPU covers 4× `p4d.24xlarge` (96 vCPU each).
- **Spot G&VT is 0** — a spot-based cost strategy needs a quota increase first.
- eu-north-1 has zero GPU quota, so the H100s there are not reachable today.

Other prerequisites confirmed present: default VPC `vpc-0abf5add40b8be118`, and the
Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) at
`ami-0b0398c9233dd8b89`, which ships the driver, container toolkit and Docker.

---

## Costs

Live on-demand and standard-RI pricing, eu-central-1, Linux/shared, as at
2026-08-25. Monthly = 730 h, storage included. For what the deployed instance
actually costs on its schedule, see
[`docs/apertus-endpoint.md`](../../docs/apertus-endpoint.md).

### 8B always-on, 1 instance

| Instance | GPU | On-demand/mo | 1-yr RI/mo | 3-yr RI/mo | On-demand/yr | 3-yr RI/yr |
|---|---|---|---|---|---|---|
| `g6.xlarge` | L4 24 GB | $754 | $497 | **$356** | $8,816 | $4,046 |
| `g5.xlarge` | A10G 24 GB | $937 | $598 | $416 | $11,020 | $4,761 |
| `g6e.xlarge` | L40S 48 GB | $1,718 | $1,089 | $753 | $20,385 | $8,806 |

### 70B always-on

| Instance | GPUs | On-demand/mo | 1-yr RI/mo | 3-yr RI/mo | On-demand/yr | 3-yr RI/yr |
|---|---|---|---|---|---|---|
| `g6e.12xlarge` | 4× L40S | $9,625 | $6,081 | **$4,185** | $114,931 | $49,650 |
| `p4d.24xlarge` | 8× A100-40 | $20,074 | $12,744 | $8,597 | $240,313 | $102,595 |
| `g6e.48xlarge` | 8× L40S | $27,551 | $17,370 | $11,925 | $330,043 | $142,525 |

Reserved instances cut 35–57%, so an always-on box is exactly the workload where
they pay off. The 3-yr `g6e.12xlarge` RI needs $129,643 upfront if taken all-upfront;
the no-upfront variant is $5.67/h.

---

## Throughput estimates

**These are roofline estimates, not measurements.** Real measured figures from
the deployed instance are in
[`docs/apertus-endpoint.md`](../../docs/apertus-endpoint.md). Decode is modelled as
bandwidth-bound, prefill as compute-bound at 38% MFU, with a tensor-parallel
penalty of 15% on NVLink and 35% on PCIe.

| Model | Instance | Single stream | Batch 32 aggregate | $/1M output tokens |
|---|---|---|---|---|
| 8B v1.0 | `g5.xlarge` | ~27 tok/s | ~325 tok/s | $1.23 |
| 8B v1.0 | `g6.xlarge` | ~13 tok/s | ~163 tok/s | $1.96 |
| 8B v1.5 | `g6e.xlarge` | ~34 tok/s | ~410 tok/s | $1.58 |
| 70B v1.5 | `g6e.12xlarge` | ~11 tok/s | ~136 tok/s | $26.87 |
| 70B v1.5 | `p4d.24xlarge` | ~53 tok/s | ~638 tok/s | $11.94 |

Two things stand out:

- **The L4 (`g6.xlarge`) is a trap.** It is the cheapest box but has only 300 GB/s
  of bandwidth against the A10G's 600, so it is roughly half the speed for 80% of
  the price. `g5.xlarge` is the better cheap option.
- **L40S has no NVLink.** 4-way tensor parallelism for the 70B runs over PCIe,
  which is why `g6e.12xlarge` looks poor per token despite being the cheapest 70B
  box. `p4d.24xlarge` costs 2.1× more per hour but is ~4.7× faster, making it
  *cheaper per token* — $11.94 vs $26.87 per 1M. If the 70B is going to be busy,
  p4d is the better buy; if it will be mostly idle, g6e.12xlarge is.

Caveat: `xielu` is a custom activation and the v1.5 path runs on a fork, so
kernel-level optimisation is likely behind mainline models. Treat these as
optimistic by perhaps 10–20% until measured.

---

## NVIDIA CUDA licensing — the guide's warning

The guide says: *"If using CUDA acceleration, ensure you comply with NVIDIA's
licensing terms for using their proprietary libraries."* Checked. **For this
deployment there is no additional licence to buy and no extra cost.** Detail:

**1. The driver.** For compute workloads on G5/G6/G6e/P4d you use the NVIDIA
**Tesla / Data Center driver**, which AWS ships pre-installed in the Deep Learning
AMI. Accepting the NVIDIA Driver License Agreement happens at install/AMI launch.
This is the compute driver and carries no per-seat licence.

The often-cited *"no datacenter deployment"* clause lives in the **GeForce/Titan**
consumer driver EULA. It does not apply here: A10G, L4, L40S and A100 are all
professional/datacenter SKUs on the Tesla driver.

Two adjacent AWS driver types **do** carry strings, and we use neither:
- **GRID / vWS** drivers — for professional visualisation, separately licensed.
- **Gaming** drivers — AWS-S3-restricted and limited to gaming use.

**2. The CUDA libraries in the container.** The CUDA Toolkit EULA has no datacenter
restriction and explicitly permits redistribution of the Attachment A binaries
(cudart, cuBLAS, cuFFT, cuSPARSE, cuRAND, NPP, nvrtc, NCCL, and cuDNN runtime
`.so` files) bundled with an application — which is what the vLLM images do. The
conditions are that the application has material additional functionality beyond
the SDK, that the bundled portions are only accessed by that application, and that
the notice *"This software contains source code provided by NVIDIA Corporation"*
is included.

**3. What that means for swisstopo in practice.**
- Running vLLM on EC2 GPU instances for internal inference: **fully covered**, no
  action needed. The licence cost is inside the instance hourly rate.
- If you ever redistribute a container image containing CUDA binaries *outside*
  the organisation, you inherit the redistribution conditions above — include the
  NVIDIA notice and pass on terms no less restrictive. Internal use is not
  redistribution, so this does not apply today.
- **NVIDIA AI Enterprise** is a separate paid product. vLLM does not need it.
- One clause worth noting for a government context: CUDA is not licensed for
  "Critical Applications" — life-support, military, autonomous vehicles and similar
  safety-critical uses. Geodata search is nowhere near that line, but it is worth
  knowing the boundary exists.

The stricter licence here is not NVIDIA's — it is the **Apertus 1.5 Acceptable Use
Policy** you accept at the HF gate. That is the one to route past legal.

---

## Where the real thing lives

The exploration scripts this file used to list (`launch-8b.sh`, `docker-compose.yml`,
`nginx.conf`, `user-data.sh`, `smoke-test.sh`, `cost_model.py`) are not part of the
deployed setup and are not in this repository. They were scaffolding for the
investigation above and were superseded by the stack itself:

- [`infra/apertus-service.yaml`](../apertus-service.yaml) — the CloudFormation stack
  that actually runs: instance, security group, IAM, EventBridge schedules, and the
  boot script that syncs weights from S3 and starts vLLM.
- [`docs/apertus-endpoint.md`](../../docs/apertus-endpoint.md) — the operational card:
  addresses, schedule, API key, measured performance, cost, capacity risk.

Security posture as deployed: no SSH and no port 22 (admin access is SSM Session
Manager), two ingress rules only, encrypted EBS, IMDSv2 required, no HuggingFace
token anywhere on the instance, and a vLLM API key so the endpoint is never
unauthenticated even on a private address.
