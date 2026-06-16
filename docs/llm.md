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

For the initial setup we use **Claude Opus 4.8** — Bedrock model ID
`eu.anthropic.claude-opus-4-8`. A frontier hosted model like Claude is the
fastest way to get a capable agent in place and test feasibility: it is strong
at the agentic tool-use and multilingual reasoning this backend depends on, and
the managed Bedrock EU endpoint removes the operational burden of self-hosting —
while leaving the door open to switch to another provider or a self-hosted
open-weights model once requirements firm up.
