# Apertus endpoint — live details

Deployed 2026-08-27 as CloudFormation stack **`sgs-llm-apertus`** in `eu-central-1`.
This is the operational card: how to reach it, when it is up, what it costs and
how to integrate. Background and licensing are in
[`infra/apertus/README.md`](../infra/apertus/README.md).

## Connect

| | |
|---|---|
| **From the backend (VPC)** | `http://172.31.32.71:8000/v1` |
| **From the office** | `http://63.182.197.164:8000/v1` — from the askEarth static gateway IP only |
| **`model` field** | `apertus-8b` |
| **Auth** | `Authorization: Bearer <key>` |
| **API key** | SSM `/apertus/api-key` (SecureString) — read it, don't copy it around |
| **Instance** | `i-0b416ac06d01fc84f`, `g6.2xlarge`, `eu-central-1b` |
| **Protocol** | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |
| **Context** | 28,000 tokens (prompt + output), 1 request at a time |

Both addresses are stable. The private IP survives stop/start because it is the
instance's primary private address; the office one is an Elastic IP, allocated
precisely because an auto-assigned public IP is released on stop and would
otherwise change every morning.

```bash
KEY=$(aws ssm get-parameter --region eu-central-1 --name /apertus/api-key \
        --with-decryption --query Parameter.Value --output text)
curl -s http://63.182.197.164:8000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"apertus-8b","messages":[{"role":"user","content":"Grüezi!"}],"max_tokens":50}'
```

## When it is up

**Weekdays 06:30–19:00 Europe/Zurich. Down every night and all weekend.**

| | |
|---|---|
| Starts | `cron(30 6 ? * MON-FRI *)` Europe/Zurich |
| Stops | `cron(0 19 ? * MON-FRI *)` Europe/Zurich |
| Ready by | ~06:35 — cold start is 4 min 48 s from a stop |
| Mechanism | EventBridge Scheduler → `ec2:StartInstances` / `StopInstances` |
| Schedules | `sgs-llm-apertus-start`, `sgs-llm-apertus-stop` (both ENABLED) |

The timezone is set on the schedule itself, so CET/CEST is handled per firing —
no DST drift.

**Out of hours the endpoint refuses connections. That is normal, not an
incident.** Anything monitoring this needs to know the schedule or it will page
someone every evening at 19:00.

Manual override:

```bash
aws ec2 start-instances --region eu-central-1 --instance-ids i-0b416ac06d01fc84f
aws ec2 stop-instances  --region eu-central-1 --instance-ids i-0b416ac06d01fc84f
```

Starting manually takes **~5 minutes to serve**. `instance-status-ok` fires at
about 2 minutes, well before vLLM accepts requests — poll `/v1/models` or
`/health`, don't trust the EC2 state.

To suspend scheduling without deleting it, set the stack's `ScheduleEnabled`
parameter to `DISABLED`.

## The API key

vLLM runs with `--api-key`, so every request needs `Authorization: Bearer <key>`.
One shared key, held in SSM at `/apertus/api-key` as a `SecureString`. It is not
in the repo, the task definition or CI.

From a workstation, read it — don't copy it around:

```bash
aws ssm get-parameter --region eu-central-1 --name /apertus/api-key \
    --with-decryption --query Parameter.Value --output text
```

Only the `admin-poc-sgs-llm` SSO role can do that today; `sgs-llm-dev` has
nothing reaching Parameter Store.

**The backend does not fetch it from SSM.** `sgs-llm-backend-task` has no
`ssm:GetParameter`, and the fix was not to grant it: `backend-service.yaml`
injects it through the task definition's `Secrets:` block, from the Secrets
Manager secret both task roles can read — the same path `MCP_SERVER_TOKEN` uses.
`APERTUS_API_KEY` arrives as an ordinary environment variable, so this needed
**no IAM change at all**.

That `Secrets:` entry is gated on the `ApertusBaseUrl` stack parameter being
non-empty. This is not tidiness: a `Secrets:` entry naming a key the secret does
not hold fails **every** task start, which would take the chat down rather than
just Apertus. Apertus is off by default for that reason, and switching it on means
confirming the key is in the secret first.

Rotating means updating both copies and restarting the container, since the key
is passed to vLLM at container start.

## How the backend uses it

`model: "apertus"` on a `user_message` pins the whole turn to this endpoint
([`protocol.md`](./protocol.md)). It is a third choice alongside Claude and
Mistral, not a replacement for either, and it is **explicit-only in both
directions**:

- An unpinned turn is never served by Apertus. Answering a Claude request with a
  self-hosted Swiss model would change the model and the residency story without
  the caller asking for either.
- A turn pinned to Apertus is never served by Bedrock. When the endpoint is
  closed, the turn ends with `error` `model_unavailable` and a localized message
  naming the schedule. Substituting Claude would make the comparison worthless,
  since the point of selecting Apertus is to see what Apertus does.

Being unreachable is **not** cached. The router marks a Bedrock model unavailable
for the life of the process when it is denied, which is right for an SCP deny and
wrong here: this endpoint returns on its own at 06:30, and caching it dead would
keep it dead until the ECS task was replaced.

Three settings differ from the Bedrock path, all in the environment contract
([`deployment.md`](./deployment.md#environment-contract)):

| | Bedrock | Apertus |
| --- | --- | --- |
| Turn budget | 90 s | 240 s (`APERTUS_TURN_TIMEOUT_SECONDS`) |
| Completion cap | 2048 | 2048 (`APERTUS_MAX_TOKENS`), charged against the context window at admission |
| Credential | task IAM role | `APERTUS_API_KEY` bearer token |

Evaluate it on the same question set with `python evals/run.py --model apertus`
([`evals.md`](./evals.md)); the harness gives it the wider budget automatically.

## What the agent loop needs from the window

Why 4096 was not merely tight but unusable, and what the 28,000-token
configuration buys — the budget arithmetic itself is in
[*Context and concurrency are the same budget*](#context-and-concurrency-are-the-same-budget).

Every request carries a fixed floor before the user has said anything:

| Fixed part of every request | Chars |
| --- | ---: |
| System prompt (`backend/app/agent/prompts.py`) | 6,659 measured on the wire |
| Tool definitions and JSON schemas | ~770 per tool; ~7,700 for the 10-tool geosearch surface |
| **Floor, before the user's question** | **~14,300** ≈ 3,600-4,100 tokens |

The backend is stateless on top of that: the client's history and every
accumulated `toolResult` are re-sent on each of up to 8 iterations, so input grows
monotonically within one turn. At 4096, with a 2048-token completion reservation
charged at admission, the prompt allowance was ~2,048 tokens — less than the
system prompt alone — so every request was rejected before the model generated
anything.

At 28,000 the same floor leaves roughly 24,000 tokens for history and tool
results, which is what makes the loop run with the full tool set rather than a
reduced one. Character counts are measured; token figures are chars ÷ 3.5-4, and
the conclusion does not depend on the ratio.

`--enable-prefix-caching` is set for the same reason. The floor is byte-identical
on every iteration of every turn, so caching that prefix removes most of the
repeated prefill. It is worth having rather than load-bearing: long prefill was
measured at ~5,200 tok/s, so re-prefilling a 26k prompt eight times costs about
40 s, not the ~99 s a naive extrapolation from the ~2,100 tok/s small-prompt
figure suggests. The flag lives in run-once `UserData`, so it applies at the next
container recycle and does not justify one of its own.

## Measured performance on this hardware

Deployed on an **L4** (`g6.2xlarge`), not the A10G that was benchmarked during
evaluation — see *Why L4* below.

| | L4 (deployed) | A10G (evaluated) |
|---|---|---|
| Single stream | **16.8 tok/s** | 30.0 tok/s |
| 4 concurrent, aggregate | **64.5 tok/s** | 118.3 tok/s |
| Prefill | ~2,100 tok/s | ~2,824 tok/s |
| KV cache | 3.47 GiB / 28,400 tokens | 3.5 GiB / 28,656 tokens |

The 4-concurrent row measures the earlier `4096 / 4` configuration. As deployed
today there is no batching, so aggregate throughput *is* the single-stream
figure — that is the trade described next.

### Context and concurrency are the same budget

`--max-model-len` is the **total** sequence length — prompt plus generated
output, not an output cap. A request whose prompt alone exceeds it is rejected.

The ceiling is the KV cache, not the model: Apertus v1.5 itself supports 262,144
tokens. On this card the weights take 17.23 GiB of the ~21.3 GiB budget, leaving
3.47 GiB of KV cache at 128 KiB per token, so the pool is **~28,400 tokens
total, shared across all in-flight requests**.

This deployment spends that pool on **one long conversation**: `max-model-len
28000`, `max-num-seqs 1`. The trade is real — with no batching, a second caller
**queues behind the first** rather than interleaving, and at ~17 tok/s that means
waiting out the whole preceding answer. Switch back to `4096 / 4` if more than
one person uses it at a time; both are stack parameters.

Note the ceiling barely moves either way: even at `max-num-seqs 1` it is ~28K,
not 262K. Real long context needs a bigger card.

**Verified on the deployed instance** after the change: vLLM reports
`GPU KV cache size: 28,400 tokens` and `Maximum concurrency for 28,000 tokens
per request: 1.01x` — it fits, with about 1% headroom. A 26,103-token prompt was
accepted and answered correctly in 5 s. Long prefill is *more* efficient than
short: ~5,200 tok/s at 26K against the ~2,100 tok/s measured on small prompts,
because a large prefill keeps the GPU better occupied.

If you ever raise `MaxModelLen` past ~28,400 the container will refuse to start
rather than degrade quietly — the failure is visible in `docker logs`.

**A 400-token answer takes about 24 seconds.** That is slow enough that users
will feel it; streaming is worth turning on. Roughly half the A10G's speed,
because the L4 has 300 GB/s of memory bandwidth against the A10G's 600 and
decode is bandwidth-bound.

Known headroom: vLLM logs `CUDA-fused xIELU not available — falling back to a
Python version`. The activation is unoptimised. Baking
`pip install git+https://github.com/nickjbrowning/XIELU` into the image should
lift this.

## Why L4 and not A10G

Frankfurt GPU capacity was exhausted during deployment. Across roughly an hour,
`g5.xlarge`, `g5.2xlarge`, `g5.4xlarge` and `g6e.xlarge` returned
`InsufficientInstanceCapacity` in **all three** AZs — each error helpfully
suggesting an AZ that was itself full by the time it was tried. `g6` (L4) was
the only family with capacity, and it had it in all three AZs consistently.

Instance type is a stack parameter. To move to A10G when capacity returns:

```bash
aws cloudformation update-stack --stack-name sgs-llm-apertus \
  --use-previous-template --capabilities CAPABILITY_IAM \
  --parameters ParameterKey=InstanceType,ParameterValue=g5.xlarge \
               ParameterKey=VpcId,UsePreviousValue=true \
               ParameterKey=SubnetId,UsePreviousValue=true \
               ParameterKey=BackendStackName,UsePreviousValue=true \
               ParameterKey=OfficeCidr,UsePreviousValue=true
```

That replaces the instance, so the private IP and the 18 GB of weights are both
lost — the new instance re-downloads and gets a new private address. The Elastic
IP follows automatically.

## The capacity risk, stated plainly

**A morning start can fail.** `StartInstances` needs capacity in the instance's
AZ just like a fresh launch does, and the instance is pinned to `eu-central-1b`
because its EBS volume is. If `g6.2xlarge` is full in 1b at 06:30, the start
fails and the endpoint simply is not there.

Mitigations in place: both schedules carry a retry policy of 5 attempts over an
hour, so a transient shortage is likely to resolve itself.

Not in place, and worth deciding on:

- **An On-Demand Capacity Reservation** guarantees the capacity, but bills 24/7
  whether the instance runs or not — which costs the same as never scaling down
  and erases the entire office-hours saving. Not recommended.
- **A baked AMI plus an Auto Scaling group across all three AZs** would let a
  failed AZ fall back to another. This is the robust answer if the endpoint ever
  becomes something people depend on, and it is a redesign rather than a
  parameter change.
A failed morning start is indistinguishable, from the backend's side, from the
ordinary overnight closure: the turn ends with `model_unavailable` and the user is
told when the model returns. Falling back to Bedrock was considered and rejected —
see *How the backend uses it* above. That keeps a failed start a visible
degradation of one model rather than a silent substitution, which is the right
trade for an evaluation pilot.

## Cost

`g6.2xlarge` at USD 1.2225/h, plus a 120 GB gp3 volume and an Elastic IP that
both bill while stopped.

| | CHF/mo |
|---|---:|
| Office hours, 10 h × 22 d | **~229** |
| Floor when stopped (EBS + EIP) | ~12 |
| Same box always-on, for comparison | ~735 |

Slightly cheaper than the g5.xlarge plan (CHF 234) despite the different
instance, because g6.2xlarge is marginally cheaper per hour than g5.xlarge.

Scheduling is what makes this affordable: roughly **CHF 500/month saved**, about
a 70% cut against always-on. A 3-year Reserved Instance would cost ~CHF 337/month
always-on, so on-demand plus the schedule wins below about 315 h/month
(10.5 h/day) — and commits to nothing.

## Security

- No SSH key and no inbound port 22. Admin access is SSM Session Manager.
- Two ingress rules only: the backend's task security group `sg-0890c6a0bb344e749`,
  and the askEarth static gateway IP as a `/32`. Everything else is refused.
- The `/32` is a filter, not authentication — the vLLM API key is what actually
  protects the endpoint. Anything sharing that office egress IP still needs the key.
- Egress is currently open, for the image pull and weight download. Narrow it
  once the weights are mirrored to S3.
- IMDSv2 required, EBS encrypted.

## Weights come from S3, not HuggingFace

The model is mirrored to a private, encrypted, public-access-blocked bucket in
the same region:

```
s3://sgs-llm-apertus-weights-259789526488/models/Apertus-v1.5-8B/
14 objects, 18.44 GB
```

At boot the instance syncs that prefix to `/opt/models/apertus` and vLLM is
pointed at the local directory. The container runs with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` and carries no `HF_TOKEN`, so nothing on the box can
reach huggingface.co even by accident.

**There is no HuggingFace token in this account any more.** `/apertus/hf-token`
was deleted; only `/apertus/api-key` remains. Verified after a full stop/start:
the endpoint came back serving in about 5 minutes with the token absent.

The instance role has **read-only** access to that prefix. Seeding the bucket is
a one-off performed with elevated credentials, not something the instance may do.

### A brand-new setup still needs a token, once

`WeightsS3Uri` empty switches the stack back to the HuggingFace path, which is
the only way to populate an empty account:

1. Put a gated-repo read token at `/apertus/hf-token` as a `SecureString`. The HF
   account behind it must have accepted the gate on the model page — acceptance
   is per account, not per token, and it also accepts the Apertus Acceptable Use
   Policy.
2. Deploy with `WeightsS3Uri=''`. The instance downloads ~18 GB from HuggingFace.
3. Seed the bucket from that instance, dereferencing the HF cache symlinks so the
   mirror is a flat 18 GB rather than a 37 GB double:

   ```bash
   SNAP=$(ls -d /opt/hfcache/hub/models--swiss-ai--Apertus-v1.5-8B/snapshots/*/ | head -1)
   mkdir -p /opt/models/apertus && cp -rL "$SNAP." /opt/models/apertus/
   aws s3 sync /opt/models/apertus/ s3://<bucket>/models/Apertus-v1.5-8B/
   ```

   The instance role is read-only, so attach a temporary write policy for this
   step and remove it afterwards.
4. Update the stack with `WeightsS3Uri` set, recycle the container, then delete
   `/apertus/hf-token`. From here the token is never needed again and can be
   revoked at HuggingFace.

Mirror cost is about USD 0.45/month of S3 Standard.

## Open items

1. **Bake the xIELU CUDA kernel** into the image. vLLM logs `CUDA-fused xIELU not
   available - falling back to a Python version`, so the measured throughput is
   below what the hardware can do.
2. **Move the vLLM flags out of run-once `UserData`.** `MaxModelLen`,
   `MaxNumSeqs` and the rest are baked into the instance's first-boot script,
   which self-guards on the container already existing and never re-runs. Changing
   any of them means either a CloudFormation instance replacement or a manual
   `docker rm -f apertus-vllm` and re-run over SSM — after which the running
   container no longer matches the template. A systemd unit or a small config file
   synced from S3 would make the flags re-read on boot.
3. **Narrow egress.** It is still open for the ghcr.io image pull and SSM. An S3
   gateway endpoint plus a ghcr.io-only rule would close most of it.
4. **Move to A10G** when `g5` capacity returns in Frankfurt, for roughly double
   the throughput. One parameter change, but it replaces the instance.
