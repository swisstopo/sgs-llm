# Deployment (POC, AWS)

The prototype is deployed to the Swisstopo POC AWS account
(`swisstopo-poc-sgs-llm`, `259789526488`) as a static frontend on S3 + CloudFront,
with the mock-agent backend on a single EC2 instance behind the same CloudFront
distribution. One HTTPS domain serves everything, so the browser only ever talks
to a single TLS origin (no mixed-content, no CORS surprises, `wss://` works).

**Live URL:** https://denpw8uo5zpkl.cloudfront.net/

```
                 ┌──────────────── CloudFront (HTTPS / wss, *.cloudfront.net) ──────────────┐
 browser ──────▶ │  default behavior            ── S3 origin (private, OAC) → dist/ + config.json │
                 │  /ws/v1, /feedback, /data/*  ── EC2 origin (http :8787)  → mock-agent          │
                 └────────────────────────────────────────────────────────────────────────────┘
```

- **TLS** is terminated at CloudFront with the default `*.cloudfront.net`
  certificate — no custom domain or ACM cert needed.
- The EC2 origin is reached over HTTP on port `8787`; CloudFront adds
  `X-Forwarded-Proto: https` (custom origin header) and forwards the viewer
  `Host` (AllViewer origin-request policy). The mock-agent uses those to emit
  `https://<cloudfront-domain>/data/...` URLs (see `mock-agent/server.mjs`).
- The agent path behaviors use the managed **CachingDisabled** cache policy and
  **AllViewer** origin-request policy; `AllowedMethods` includes `POST` for
  `/feedback`. The default (S3) behavior uses **CachingOptimized**.
- SPA fallback: CloudFront custom error responses map `403`/`404` → `/index.html`
  (`200`).

## Region note

Deployed in **eu-central-1 (Frankfurt)**. The originally intended
**eu-central-2 (Zurich)** is an opt-in region and is currently **DISABLED** on
this account; enabling it (`aws account enable-region --region-name eu-central-2`)
and waiting for activation is required before deploying there. For the POC the
only data in play is public geo.admin.ch tiles and mock demo data, so Frankfurt
is acceptable. Move to Zurich for the production system.

## Resource inventory

| Resource | ID / value |
| --- | --- |
| Region | `eu-central-1` |
| S3 bucket (private) | `sgs-llm-frontend-259789526488` |
| CloudFront distribution | `E2AEIO5QX64WCY` → `denpw8uo5zpkl.cloudfront.net` |
| CloudFront OAC | `E3NND1A7M7LYCH` |
| EC2 instance (`t3.small`, AL2023) | `i-08d1b778054ff9fdf` |
| Security group | `sg-028f6864ebde6e4b8` (TCP 8787 from CloudFront prefix list `pl-a3a144ca` + an admin IP) |

Everything is tagged `project=sgs-llm-poc`.

## One-time credential setup

The account is accessed via IAM Identity Center (SSO). From the AWS access portal
→ **Access keys**, copy the short-lived credentials into a named profile in
`~/.aws/credentials` (leave `[default]` alone):

```ini
[swisstopo]
aws_access_key_id = ASIA...
aws_secret_access_key = ...
aws_session_token = ...
```

These expire (re-copy when commands return `ExpiredToken`). Verify:

```bash
aws sts get-caller-identity --profile swisstopo   # Account: 259789526488
```

All commands below take `--profile swisstopo`.

## Redeploy the frontend

```bash
PROFILE=swisstopo ./scripts/deploy-frontend.sh
```

Builds `frontend/`, syncs `dist/` to S3 (fingerprinted assets cached immutably,
`index.html` no-cache), and invalidates CloudFront. It deliberately does **not**
overwrite `config.json`.

`config.json` (runtime endpoints) is managed separately so it can be repointed
without a rebuild:

```bash
aws s3 cp config.json s3://sgs-llm-frontend-259789526488/config.json \
  --cache-control no-store --content-type application/json --profile swisstopo
# current contents:
# { "agentWsUrl": "wss://denpw8uo5zpkl.cloudfront.net/ws/v1",
#   "feedbackUrl": "https://denpw8uo5zpkl.cloudfront.net/feedback" }
```

## Manage the mock-agent (EC2)

The instance runs the mock-agent via systemd. It pulls the code from the public
GitHub repo on first boot (cloud-init user-data) and serves on port `8787`.

```bash
# Stop the instance when not demoing (CloudFront keeps serving the static site;
# only chat/feedback go dark). Saves the t3.small hourly cost.
aws ec2 stop-instances  --instance-ids i-08d1b778054ff9fdf --profile swisstopo
aws ec2 start-instances --instance-ids i-08d1b778054ff9fdf --profile swisstopo
```

> After a start, the instance gets a **new public DNS**, so the CloudFront
> `ec2-agent` origin `DomainName` must be updated to match (or assign an Elastic
> IP / use a stable origin). To push new agent code, redeploy the instance or
> attach SSM/SSH and `git pull` in `/opt/sgs-llm` then
> `systemctl restart mock-agent`. (The instance was launched without a key pair
> or SSM role; attach an SSM instance profile if you need shell access.)

## Cost / teardown

S3 + CloudFront cost cents/month at POC traffic; the `t3.small` is the main cost
(~$15/mo) — stop it when idle. To tear everything down:

```bash
aws cloudfront get-distribution-config --id E2AEIO5QX64WCY --profile swisstopo   # disable, then delete
aws ec2 terminate-instances --instance-ids i-08d1b778054ff9fdf --profile swisstopo
aws ec2 delete-security-group --group-id sg-028f6864ebde6e4b8 --profile swisstopo
aws s3 rm s3://sgs-llm-frontend-259789526488 --recursive --profile swisstopo
aws s3api delete-bucket --bucket sgs-llm-frontend-259789526488 --profile swisstopo
aws cloudfront delete-origin-access-control --id E3NND1A7M7LYCH --profile swisstopo
```

## Follow-ups (post-POC)

- Move to eu-central-2 (Zurich) once the region is enabled.
- Replace the single EC2 with a managed/serverless backend (ECS Fargate, or
  API Gateway WebSocket + Lambda) and the mock-agent with the real agent.
- GitHub Actions deploy on merge to `main` (OIDC role, no static keys).
- Custom domain + ACM certificate.
