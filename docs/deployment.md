# Deployment (AWS)

This document describes how the SGS LLM prototype is deployed to AWS, and how to
reproduce, redeploy, operate, and tear it down. It contains **no credentials** —
where credentials are needed, only the file *structure* is shown.

**Live URL:** https://denpw8uo5zpkl.cloudfront.net/

The frontend is a static single-page app on **S3 + CloudFront**; the agent path is
served by the **ECS Fargate backend behind an ALB** through the *same* CloudFront
distribution. One HTTPS domain serves everything, so the browser only ever talks
to a single TLS origin — no mixed-content, no CORS, and `wss://` works.

```
                 ┌──────────────── CloudFront (HTTPS / wss, *.cloudfront.net) ──────────────┐
 browser ──────▶ │  default behavior            ── S3 origin (private, OAC) → dist/ + config.json │
 (https + wss)   │  /ws/v1, /feedback, /data/*  ── ALB origin (http :80) → ECS Fargate task      │
                 └────────────────────────────────────────────────────────────────────────────┘
```

The **EC2 mock-agent origin is retained but no longer in the path** — the agent
behaviors point at `alb-agent`, so rolling back is flipping three
`TargetOriginId` values. Until the agent code lands under `backend/`, the Fargate
task runs the same mock-agent as its container image, so behaviour is unchanged.
See [Backend deployment](#backend-deployment).

The geodata tools the backend calls over MCP run as a **second Fargate service in the
same ECS cluster**, with no load balancer and no public path — see
[Geodata MCP server](#geodata-mcp-server-geosearch-deployment).

Key design points:

- **TLS** is terminated at CloudFront with the default `*.cloudfront.net`
  certificate — no custom domain or ACM certificate required.
- The EC2 origin is reached over **HTTP on port 8787**. CloudFront adds an
  `X-Forwarded-Proto: https` custom origin header and forwards the viewer `Host`
  (AllViewer origin-request policy). `mock-agent/server.mjs` uses those to emit
  `https://<cloudfront-domain>/data/...` URLs that resolve same-origin.
- Agent path behaviors use the managed **CachingDisabled** cache policy and
  **AllViewer** origin-request policy; their `AllowedMethods` include `POST`
  (for `/feedback`). The default (S3) behavior uses **CachingOptimized**.
- **SPA fallback:** CloudFront custom error responses map `403`/`404` →
  `/index.html` (`200`), so client-side routes and the private-bucket OAC (which
  returns `403` for missing keys) both resolve to the app.
- **CI/CD:** every push to `main` redeploys the frontend automatically — the
  `deploy` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
  assumes a scoped IAM role via GitHub OIDC after the CI jobs pass (no AWS
  keys stored in GitHub). See [Redeploy the frontend](#redeploy-the-frontend).

## Region note

Deployed in **eu-central-1 (Frankfurt)**. The originally intended
**eu-central-2 (Zurich)** is an *opt-in* region and is currently **DISABLED** on
the account: regional calls there fail with `InvalidToken` / `AuthFailure` until
the region is enabled (`aws account enable-region --region-name eu-central-2`)
and activation completes. For the POC the only data in play is public
geo.admin.ch tiles and mock demo data, so Frankfurt is acceptable. Enable Zurich
for the production system.

**LLM (Bedrock).** Amazon Bedrock is available in both Frankfurt (`eu-central-1`)
and Zurich (`eu-central-2`), and across most EU regions. Claude is not hosted
*in-region* in Frankfurt or Zurich; it is reached through Bedrock
[cross-region inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html) —
the **EU profile** (`eu.anthropic.claude-*`) keeps every request within EU
regions (data stays in the EU, and Bedrock retains no prompts or outputs by
default), while the global profile may route worldwide. There is no
Switzerland-only Claude inference today — Stockholm is the only EU region hosting
recent Claude in-region — so the EU profile is the practical residency choice.
Trend: AWS keeps expanding sovereign options (the EU Sovereign Cloud reached GA
in Germany in early 2026) and in-region frontier-model coverage is growing, but
cross-region inference remains the way to pair frontier models with EU data
residency.

## Resource inventory (current deployment)

| Resource | ID / value |
| --- | --- |
| Account / region | `259789526488` / `eu-central-1` |
| S3 bucket (private) | `sgs-llm-frontend-259789526488` |
| CloudFront distribution | `E2AEIO5QX64WCY` → `denpw8uo5zpkl.cloudfront.net` |
| CloudFront OAC | `E3NND1A7M7LYCH` |
| EC2 instance (`t3.small`, AL2023) | `i-08d1b778054ff9fdf` |
| Security group | `sg-028f6864ebde6e4b8` — TCP 8787 from the CloudFront managed prefix list only |
| GitHub OIDC provider (IAM) | `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`) |
| CI deploy role (IAM) | `github-actions-sgs-llm-deploy` — trusted for `repo:swisstopo/sgs-llm:ref:refs/heads/main` only; inline policy `sgs-llm-frontend-deploy` |

Agent backend ([Backend deployment](#backend-deployment)) — names are fixed by the
templates; generated values come from the stack outputs:

| Resource | ID / value |
| --- | --- |
| CloudFormation stacks | `sgs-llm-backend-foundation`, `sgs-llm-backend-service` |
| ECS cluster / service | `sgs-llm` / `sgs-llm-backend` (Fargate, 4 vCPU / 8 GB, desired 1, no autoscaling) |
| ECR repository | `259789526488.dkr.ecr.eu-central-1.amazonaws.com/sgs-llm-backend` |
| ALB | `sgs-llm-backend-alb-1628441444.eu-central-1.elb.amazonaws.com` — inbound from prefix list `pl-a3a144ca` (CloudFront) only |
| Target group | `sgs-llm-backend-tg` (`/health`, HTTP 8787) |
| Network (consumed, not created) | `vpc-0abf5add40b8be118` (default VPC) · subnets `subnet-0948e33e0f3c89a56`, `subnet-04daf3587f8597662`, `subnet-0c7a22581e6edd850` |
| Security groups | `sgs-llm-backend-alb-sg` (CloudFront → 80), `sg-0890c6a0bb344e749` task SG (ALB → 8787) |
| DynamoDB tables | `sgs-llm-feedback`, `sgs-llm-conversations` (on-demand, TTL, PITR) |
| S3 bucket (data layers) | `sgs-llm-data-259789526488` (private, presigned reads) |
| CloudWatch log group | `/ecs/sgs-llm-backend` (30 days) |
| Secret | `sgs-llm/backend` (MCP token; placeholder until MCP lands) |
| Task roles (IAM) | `sgs-llm-backend-task`, `sgs-llm-backend-task-execution` |
| CI deploy role (IAM) | `github-actions-sgs-llm-backend-deploy` — same repo/branch trust, scoped to ECR push + rolling the one service |
| Developer role (IAM) | `sgs-llm-dev` — Bedrock inference + read-only tables, restricted to one source IP |

Geodata MCP server ([Geodata MCP server](#geodata-mcp-server-geosearch-deployment)) — **not
yet deployed**; the names below are fixed by the templates, the generated values are not:

| Resource | ID / value |
| --- | --- |
| CloudFormation stacks | `sgs-llm-geosearch-foundation`, `sgs-llm-geosearch-service` |
| ECS cluster / service | `sgs-llm` — **the same cluster as the backend** / `sgs-llm-geosearch` (Fargate, 2 vCPU / 4 GB, desired 1, capped at 1) |
| ECR repository | `259789526488.dkr.ecr.eu-central-1.amazonaws.com/sgs-llm-geosearch` |
| Load balancer | **none** — ECS Service Connect only, at `sgs-llm-geosearch:8790` |
| Cloud Map namespace | `sgs-llm` (**HTTP**, not private DNS — the account denies `route53:CreateHostedZone`) |
| S3 bucket (search index) | `sgs-llm-index-259789526488` (versioned, no expiry — CI builds the image from it) |
| S3 bucket (data layers) | `sgs-llm-data-259789526488` — **shared with the backend**, so a layer either service publishes is served the same way |
| Security group | task SG admitting the backend's task SG on 8790, and nothing else |
| CloudWatch log group | `/ecs/sgs-llm-geosearch` (30 days) |
| Task roles (IAM) | `sgs-llm-geosearch-task`, `sgs-llm-geosearch-task-execution` |
| CI deploy role (IAM) | `github-actions-sgs-llm-geosearch-deploy` — same repo/branch trust, scoped to its own ECR repo, its own service, and read on the index bucket |

Everything is tagged `project=sgs-llm-poc`.

## Prerequisites

> Routine frontend **and backend** deploys need **none of this** — they run
> automatically from GitHub Actions on push to `main`. The prerequisites below are
> for manual deploys, EC2 operation, and infrastructure changes.

- **AWS CLI v2**, **GitHub CLI** (`gh`), **Node.js 22**; **Docker** for manual
  backend image builds.
- Access to the AWS account via IAM Identity Center (SSO) with an admin role.
- A named AWS CLI profile (the examples use `swisstopo`). From the AWS access
  portal → **Access keys**, copy the short-lived credentials into a profile in
  `~/.aws/credentials`, leaving `[default]` untouched. **Do not commit this file.**

  ```ini
  [swisstopo]
  aws_access_key_id = <from access portal>
  aws_secret_access_key = <from access portal>
  aws_session_token = <from access portal>
  ```

  These are temporary and expire (re-copy when commands return `ExpiredToken`).
  Verify the profile points at the right account before doing anything:

  ```bash
  aws sts get-caller-identity --profile swisstopo   # Account: 259789526488
  ```

All commands below take `--profile swisstopo`.

## Reproduce from scratch

Shared variables used throughout:

```bash
PROFILE=swisstopo
REGION=eu-central-1
ACCOUNT=259789526488
BUCKET=sgs-llm-frontend-$ACCOUNT
```

### 1. Build the frontend

```bash
cd frontend
npm ci
npm run build          # type-check + production build → frontend/dist/
cd ..
```

### 2. Private S3 bucket + Origin Access Control

```bash
# Bucket (note: every region except us-east-1 needs LocationConstraint)
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" --profile "$PROFILE"

# Keep it fully private — CloudFront reads it via OAC, never the public internet
aws s3api put-public-access-block --bucket "$BUCKET" --profile "$PROFILE" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-tagging --bucket "$BUCKET" --profile "$PROFILE" \
  --tagging 'TagSet=[{Key=project,Value=sgs-llm-poc}]'

# Upload the build (config.json is overwritten in step 5)
aws s3 sync frontend/dist/ "s3://$BUCKET/" --delete --profile "$PROFILE"

# CloudFront Origin Access Control (S3, SigV4)
aws cloudfront create-origin-access-control --profile "$PROFILE" \
  --origin-access-control-config \
  Name=sgs-llm-oac,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3 \
  --query 'OriginAccessControl.Id' --output text          # → OAC id
```

### 3. EC2 mock-agent

The instance pulls the (public) repo on first boot via cloud-init user-data and
runs the mock-agent under systemd on port 8787. Its security group allows 8787
**only from CloudFront** (the managed prefix list), so the origin is not openly
reachable.

```bash
# Discover the building blocks
AMI=$(aws ssm get-parameters --profile "$PROFILE" --region "$REGION" \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)
VPC=$(aws ec2 describe-vpcs --profile "$PROFILE" --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNET=$(aws ec2 describe-subnets --profile "$PROFILE" --region "$REGION" \
  --filters Name=vpc-id,Values=$VPC Name=default-for-az,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
PL=$(aws ec2 describe-managed-prefix-lists --profile "$PROFILE" --region "$REGION" \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)

# Security group: inbound 8787 from CloudFront only
SG=$(aws ec2 create-security-group --profile "$PROFILE" --region "$REGION" \
  --group-name sgs-llm-mock-agent --description "SGS LLM mock-agent (CloudFront origin)" \
  --vpc-id "$VPC" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --profile "$PROFILE" --region "$REGION" \
  --group-id "$SG" \
  --ip-permissions "IpProtocol=tcp,FromPort=8787,ToPort=8787,PrefixListIds=[{PrefixListId=$PL}]"

# user-data: install Node, clone the repo, run mock-agent via systemd
cat > userdata.sh <<'EOF'
#!/bin/bash
set -xe
dnf install -y git nodejs
git clone https://github.com/swisstopo/sgs-llm /opt/sgs-llm
cd /opt/sgs-llm/mock-agent
npm ci --omit=dev || npm install --omit=dev
cat >/etc/systemd/system/mock-agent.service <<'UNIT'
[Unit]
Description=SGS LLM mock-agent
After=network.target
[Service]
WorkingDirectory=/opt/sgs-llm/mock-agent
ExecStart=/usr/bin/node server.mjs
Environment=PORT=8787
Restart=always
User=root
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mock-agent
EOF

# Launch
IID=$(aws ec2 run-instances --profile "$PROFILE" --region "$REGION" \
  --image-id "$AMI" --instance-type t3.small --subnet-id "$SUBNET" \
  --security-group-ids "$SG" --associate-public-ip-address \
  --user-data file://userdata.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=project,Value=sgs-llm-poc},{Key=Name,Value=sgs-llm-mock-agent}]' \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --profile "$PROFILE" --region "$REGION" --instance-ids "$IID"
aws ec2 describe-instances --profile "$PROFILE" --region "$REGION" --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text   # → EC2 public DNS
```

### 4. CloudFront distribution

Create the distribution with two origins (S3 via OAC + the EC2 public DNS) and
the cache behaviors described above. The full config is in
[Appendix: CloudFront distribution config](#appendix-cloudfront-distribution-config)
— fill in the S3 regional domain, the OAC id, and the EC2 public DNS, then:

```bash
aws cloudfront create-distribution --profile "$PROFILE" \
  --distribution-config file://cf-dist.json \
  --query 'Distribution.[Id,DomainName,ARN]' --output text         # → id, domain, ARN
```

Then grant **only this distribution** read access to the bucket (replace
`<DIST_ARN>`):

```bash
cat > bucket-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowCloudFrontOAC",
    "Effect": "Allow",
    "Principal": { "Service": "cloudfront.amazonaws.com" },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::$BUCKET/*",
    "Condition": { "StringEquals": { "AWS:SourceArn": "<DIST_ARN>" } }
  }]
}
EOF
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file://bucket-policy.json --profile "$PROFILE"
```

### 5. Wire runtime config + wait for deploy

`config.json` is served from S3 (no rebuild needed to repoint it). Point it at the
CloudFront domain (replace `<DOMAIN>` with the distribution's `*.cloudfront.net`):

```bash
cat > config.json <<EOF
{
  "agentWsUrl": "wss://<DOMAIN>/ws/v1",
  "feedbackUrl": "https://<DOMAIN>/feedback"
}
EOF
aws s3 cp config.json "s3://$BUCKET/config.json" \
  --cache-control no-store --content-type application/json --profile "$PROFILE"

aws cloudfront wait distribution-deployed --id <DIST_ID> --profile "$PROFILE"
```

### 6. Verify

```bash
B=https://<DOMAIN>
curl -s -o /dev/null -w "site:     %{http_code}\n" "$B/"
curl -s -o /dev/null -w "deeplink: %{http_code}\n" "$B/some/route"      # SPA fallback → 200
curl -s -o /dev/null -w "data:     %{http_code}\n" "$B/data/sample-places.geojson"
curl -s -o /dev/null -w "feedback: %{http_code}\n" -X OPTIONS "$B/feedback"
curl -s -i --http1.1 \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "$B/ws/v1" | head -1                                                  # → 101 Switching Protocols
```

Then open the URL in a browser and exercise the map, the catalog, a chat query
(e.g. *"Show me flood zones in Valais"* → a layer appears on the map), and the
feedback form.

### 7. GitHub Actions OIDC deploy role (CI/CD)

One-time IAM setup that lets the `deploy` job in `ci.yml` publish without any
stored AWS keys. GitHub's OIDC token is exchanged for short-lived role
credentials; the trust is pinned to this repo's `main` branch and the
permissions to exactly the two deploy actions.

```bash
# OIDC identity provider (once per account)
aws iam create-open-id-connect-provider --profile "$PROFILE" \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  --tags Key=project,Value=sgs-llm-poc

# Role: trusted only for pushes to swisstopo/sgs-llm main
cat > trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:swisstopo/sgs-llm:ref:refs/heads/main"
      }
    }
  }]
}
EOF
aws iam create-role --profile "$PROFILE" \
  --role-name github-actions-sgs-llm-deploy \
  --assume-role-policy-document file://trust.json \
  --tags Key=project,Value=sgs-llm-poc

# Permissions: bucket sync + CloudFront invalidation, nothing else
cat > deploy-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ListFrontendBucket", "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::$BUCKET" },
    { "Sid": "WriteFrontendObjects", "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::$BUCKET/*" },
    { "Sid": "InvalidateDistribution", "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::$ACCOUNT:distribution/<DIST_ID>" }
  ]
}
EOF
aws iam put-role-policy --profile "$PROFILE" \
  --role-name github-actions-sgs-llm-deploy \
  --policy-name sgs-llm-frontend-deploy \
  --policy-document file://deploy-policy.json
```

The workflow's `deploy` job references the role ARN directly (role ARNs are
not secrets) and needs `permissions: id-token: write` — see
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Redeploy the frontend

**Automatic (default):** every push to `main` deploys via the `deploy` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), after the CI jobs
pass. The job assumes the IAM role
`arn:aws:iam::259789526488:role/github-actions-sgs-llm-deploy` through GitHub's
OIDC provider — no long-lived AWS keys in GitHub. The trust policy only accepts
tokens for `repo:swisstopo/sgs-llm:ref:refs/heads/main`, and the role's inline
policy (`sgs-llm-frontend-deploy`) only allows listing/writing the
`sgs-llm-frontend-259789526488` bucket and creating invalidations on the
distribution `E2AEIO5QX64WCY`. One-time account setup (already done): the
`token.actions.githubusercontent.com` OIDC identity provider plus that role,
both tagged `project=sgs-llm-poc`.

**Manual (fallback):**

```bash
PROFILE=swisstopo ./scripts/deploy-frontend.sh
```

Builds `frontend/`, syncs `dist/` to S3 (fingerprinted assets cached immutably,
`index.html` no-cache), and invalidates CloudFront. It deliberately does **not**
overwrite `config.json` (managed in step 5 above). `PROFILE=` (empty) makes the
script use ambient credentials — that's how the GitHub Actions job calls it.

## Operate the mock-agent (EC2)

```bash
# Stop when not demoing — CloudFront keeps serving the static site; only
# chat/feedback go dark. This saves the t3.small hourly cost.
aws ec2 stop-instances  --instance-ids i-08d1b778054ff9fdf --profile swisstopo
aws ec2 start-instances --instance-ids i-08d1b778054ff9fdf --profile swisstopo
```

> ⚠️ After a stop/start the instance gets a **new public DNS**, so the CloudFront
> `ec2-agent` origin `DomainName` must be updated to match. An Elastic IP (or a
> stable internal origin) avoids this. The instance was launched without a key
> pair or SSM role; attach an SSM instance profile if you need shell access to
> `git pull` new agent code and `systemctl restart mock-agent`.

## Cost / teardown

S3 + CloudFront cost cents/month at POC traffic; the `t3.small` (~$15/mo) is the
main cost — stop it when idle. To remove everything:

```bash
# CloudFront: disable in the console or via update-distribution, then:
aws cloudfront delete-distribution --id E2AEIO5QX64WCY --if-match <ETag> --profile swisstopo
aws ec2 terminate-instances --instance-ids i-08d1b778054ff9fdf --profile swisstopo
aws ec2 delete-security-group --group-id sg-028f6864ebde6e4b8 --profile swisstopo
aws s3 rm s3://sgs-llm-frontend-259789526488 --recursive --profile swisstopo
aws s3api delete-bucket --bucket sgs-llm-frontend-259789526488 --profile swisstopo
aws cloudfront delete-origin-access-control --id E3NND1A7M7LYCH --profile swisstopo
aws iam delete-role-policy --role-name github-actions-sgs-llm-deploy \
  --policy-name sgs-llm-frontend-deploy --profile swisstopo
aws iam delete-role --role-name github-actions-sgs-llm-deploy --profile swisstopo
aws iam delete-open-id-connect-provider --profile swisstopo \
  --open-id-connect-provider-arn arn:aws:iam::259789526488:oidc-provider/token.actions.githubusercontent.com
```

## Backend deployment

The agent backend runs as a container on **ECS Fargate behind an Application Load
Balancer**, replacing the EC2 mock-agent as the CloudFront origin for `/ws/v1`,
`/feedback` and `/data/*`. Its internal design (MCP client, the LLM loop,
data-layer artifacts) is in
[`architecture.md`](./architecture.md#backend-architecture); the model choice is in
[`llm.md`](./llm.md).

The backend **code lives in this repository** under [`backend/`](../backend/) - a Python
service (FastAPI + uvicorn) that runs the LLM loop on Bedrock and the MCP client for the
geodata tools. Because both `scripts/deploy-backend.sh` and the deploy workflow pick
`backend/Dockerfile` whenever it exists, **committing that file is what puts the real
backend into production**; no infrastructure, IAM or CloudFront change is needed. The
bundled `mock-agent/` remains the protocol reference implementation and the rollback
image.

Two properties make that switch safe to do unattended: the image starts healthy with no
AWS credentials, no DynamoDB tables and no MCP server configured (which is exactly how CI
smoke-tests it), and the ECS deployment circuit breaker rolls back a task that never
becomes healthy.

```text
                 ┌──────────────── CloudFront (HTTPS / wss) ────────────────────┐
 browser ──────▶ │  default               → S3 (private, OAC) → dist/ + config   │
 (https + wss)   │  /ws/v1 · /feedback · /data/*  → ALB origin (WebSocket upgrade)│
                 └───────────────────────────────────┬───────────────────────────┘
                                                     ▼
                              Application Load Balancer (public subnets, idle timeout 3600s,
                              inbound only from the CloudFront prefix list)
                                                     ▼
                              ECS Fargate service · 4 vCPU / 8 GB · desired count 1
                              private subnets, no public IP, egress via NAT
                                     image pulled from ECR (sgs-llm-backend)
                                     ├─► Amazon Bedrock — Claude + Mistral, EU profiles (task IAM role)
                                     ├─► DynamoDB — user feedback + conversation turns
                                     ├─► S3 — data-layer artifacts; backend relays presigned URLs
                                     └─► geosearch — the geodata MCP server, a second Fargate
                                         service in the SAME cluster, reached over Service Connect
                                         (see "Geodata MCP server" below)
```

- **ECS on Fargate behind an ALB** — managed containers with native WebSocket and zero-downtime rolling deploys (the Azure Container Apps analogue).
- **Amazon ECR** (private) — the registry the service pulls from, scan-on-push, last 20 images kept.
- **Reuse the existing CloudFront distribution** — the agent path behaviors point at the ALB; one TLS origin keeps `wss://` working and leaves the S3 / `config.json` path untouched.
- **ALB locked to the CloudFront managed prefix list** (`com.amazonaws.global.cloudfront.origin-facing`) — the origin is unreachable except through CloudFront, mirroring the EC2 security group.
- **ALB idle timeout 3600 s** — long-lived chat connections survive quiet periods mid-conversation.
- **Existing VPC, no network topology created** — see [Network constraint](#network-constraint-no-vpc-creation-in-this-account). The stack consumes a VPC id and subnet ids; the tasks run in the default VPC's public subnets with `AssignPublicIp: ENABLED`, and are reachable only through the ALB security group.
- **Task IAM role for Bedrock** (`bedrock:InvokeModel` / `InvokeModelWithResponseStream` on the EU inference profiles) — model access with no API key to store. Secrets Manager holds only non-AWS credentials such as the MCP server token.
- **Deployment circuit breaker with rollback** — a task that never becomes healthy rolls the service back to the previous task definition automatically, so an unattended bad deploy cannot leave the service down.

### Pilot phase

A **single Fargate task** (desired count 1, autoscaling deliberately off) at
**4 vCPU / 8 GB** — sized with headroom so the agent loop, MCP calls and
concurrent WebSocket sessions are not the thing that needs debugging first. Going
to production means raising the desired count and enabling autoscaling on the
service; the ALB is unchanged by that. Set the desired count to **0** to park the
service without deleting anything.

### Network constraint: no VPC creation in this account

The POC account's `AccountAdmin` policy (attached to the IAM Identity Center admin
role) carries an **explicit deny** on essentially all network-topology creation:

```text
ec2:CreateVpc, CreateSubnet, CreateRouteTable, CreateRoute, CreateNatGateway,
CreateInternetGateway, AttachInternetGateway, AssociateRouteTable,
ModifySubnetAttribute, CreateVpnGateway, CreateEgressOnlyInternetGateway, …
```

An explicit deny cannot be overridden by any identity-based Allow, so **not even an
account administrator can create a VPC, a subnet or a NAT gateway here**. (The same
policy also denies writes to `swisstopo-poc-sgs-llm-terraform-state`, which
suggests network topology is provisioned centrally for this account.) The
consequences for this deployment:

- The stack takes `VpcId` and `SubnetIds` as **parameters** and creates no network
  resources. In the POC account these are the **default VPC** (`vpc-0abf5add40b8be118`,
  `172.31.0.0/16`) and its three default subnets — the same network the EC2
  mock-agent already runs in.
- Those subnets are public, and a NAT gateway cannot be created, so the service
  runs with **`AssignPublicIp: ENABLED`**. That is not optional: without it a
  Fargate task in these subnets cannot reach ECR to pull its image, let alone
  Bedrock or DynamoDB.
- **Security is unchanged by this.** The task's security group admits traffic from
  the ALB security group only, and the ALB's admits only the CloudFront
  origin-facing prefix list. Verified after deployment: a direct request to the ALB
  from the public internet times out. The task has a public IP but no inbound path,
  exactly like the EC2 mock-agent.

If a private-subnet topology is wanted later (the original intent), it has to come
from whoever owns the account guardrail: either the network is pre-provisioned for
this project and passed in via `SubnetIds`, or the deny is relaxed. Nothing in
these templates needs to change for that — only the parameter values.

### Prerequisite: the ECS service-linked role

ECS had never been used in this account. Creating the service occasionally fails
with `Unable to assume the service linked role` on a fresh account; if that
happens, create it once and redeploy:

```bash
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com --profile swisstopo
```

### Infrastructure: two CloudFormation stacks

| Stack | Template | Contents |
| --- | --- | --- |
| `sgs-llm-backend-foundation` | [`infra/backend-foundation.yaml`](../infra/backend-foundation.yaml) | ALB + target group + listener, security groups, ECR repository, both DynamoDB tables, data-layer S3 bucket, CloudWatch log group, Secrets Manager placeholder, all four IAM roles. Consumes an existing VPC/subnets — see [Network constraint](#network-constraint-no-vpc-creation-in-this-account) |
| `sgs-llm-backend-service` | [`infra/backend-service.yaml`](../infra/backend-service.yaml) | ECS cluster, task definition (sizing + the environment contract), Fargate service |

Two stacks rather than one because **an ECS service cannot be created before an
image exists in ECR**, and ECR is itself part of the infrastructure. The
foundation stack is deployed once and then left alone; the service stack is
created once and thereafter bypassed by routine deploys (CI registers task
definition revisions directly — see [Deploy the backend code](#deploy-the-backend-code)).

The DynamoDB tables and the data-layer bucket carry `DeletionPolicy: Retain`:
they hold user-submitted content, not disposable infrastructure, so deleting a
stack never deletes them (teardown does it explicitly).

#### Deploy the infrastructure

```bash
PROFILE=swisstopo
REGION=eu-central-1

# The ALB accepts traffic from CloudFront and nowhere else; the prefix list id
# is region-specific.
PL=$(aws ec2 describe-managed-prefix-lists --profile "$PROFILE" --region "$REGION" \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)

# Network is consumed, not created (see Network constraint above).
VPC=$(aws ec2 describe-vpcs --profile "$PROFILE" --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --profile "$PROFILE" --region "$REGION" \
  --filters Name=vpc-id,Values="$VPC" --query 'Subnets[].SubnetId' --output text | tr '\t' ',')

# The developer-access IP is deliberately not stored in this repository.
# See infra/dev-access.env.example.
source infra/dev-access.local.env      # sets DEV_ACCESS_CIDR

aws cloudformation deploy --profile "$PROFILE" --region "$REGION" \
  --stack-name sgs-llm-backend-foundation \
  --template-file infra/backend-foundation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --tags project=sgs-llm-poc \
  --parameter-overrides \
    VpcId="$VPC" \
    SubnetIds="$SUBNETS" \
    CloudFrontPrefixListId="$PL" \
    DevAccessCidr="$DEV_ACCESS_CIDR"

# Publish the first image (the mock-agent bootstrap) so the service can start.
BUILD_ONLY=1 PROFILE="$PROFILE" ./scripts/deploy-backend.sh

aws cloudformation deploy --profile "$PROFILE" --region "$REGION" \
  --stack-name sgs-llm-backend-service \
  --template-file infra/backend-service.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --tags project=sgs-llm-poc \
  --parameter-overrides \
    ImageTag=<tag pushed above> \
    PrimaryModelId=eu.anthropic.claude-sonnet-4-6 \
    SecondaryModelId=mistral.ministral-3-14b-instruct \
    SecondaryModelRegion=eu-west-1
```

Then repoint CloudFront at the ALB (see
[Cut CloudFront over to the backend](#cut-cloudfront-over-to-the-backend)).

> ⚠️ **Use [`scripts/deploy-backend-stack.sh`](../scripts/deploy-backend-stack.sh) for
> later parameter changes, not `aws cloudformation deploy`.** That command resolves each
> parameter you omit to its **template default**, not to the value currently deployed.
> `SecondaryModelId` defaults to empty, so one forgotten override silently removes the
> fallback model - and while the SCP blocks Claude that leaves every turn failing. The
> same trap applies to `ImageTag` (CI owns the running image, so the template's value is
> stale by design) and to `McpServerUrl`, which is what enables the chat at all.
>
> ```bash
> # Change one parameter; everything else keeps its deployed value.
> PROFILE=swisstopo ./scripts/deploy-backend-stack.sh McpServerUrl=https://mcp.example.ch/mcp
> DRY_RUN=1 PROFILE=swisstopo ./scripts/deploy-backend-stack.sh ApiKey=...   # plan only
> ```
>
> It sends `UsePreviousValue` for every parameter it is not asked to change, which also
> handles `ApiKey` - a `NoEcho` value reads back as `****` and must never be re-sent
> literally. Newly added template parameters (the four limits) have no previous value, so
> they are omitted and take their template defaults.
>
> This stays a human step on purpose: the CI deploy role holds
> `cloudformation:DescribeStacks` on the foundation stack only, so automating it would
> mean granting an OIDC-assumable role the power to rewrite the task definition. CI owns
> the image; humans own the stack.

### What the container image must provide

The image is the only contract between the backend code and this infrastructure:

| Requirement | Why |
| --- | --- |
| Listens on `$PORT` (8787) | Target group port and security group rule |
| `GET /health` → `200` | ALB health check; an unhealthy task is replaced and a bad deploy rolls back |
| `WebSocket /ws/v1` | Protocol v1 ([`protocol.md`](./protocol.md)) |
| `POST /feedback` | Feedback form endpoint |
| Handles `SIGTERM` | ECS stops tasks with SIGTERM (30 s stop timeout); draining beats being killed mid-conversation |
| `linux/amd64` | The task definition pins X86_64; CI builds on x86 runners |

`mock-agent/Dockerfile` satisfies all of these and is the working example.

### Environment contract

Configuration reaches the container as environment variables set by the task
definition — nothing is baked into the image, and nothing sensitive is in git.
Non-secret values come from `infra/backend-service.yaml`; secrets are injected by
ECS from Secrets Manager at task start.

| Variable | Source | Meaning |
| --- | --- | --- |
| `PORT` | parameter (8787) | Port to listen on |
| `LOG_LEVEL` | parameter (`info`) | Application log level |
| `AWS_REGION` / `BEDROCK_REGION` | stack region / parameter | Region the SDK and the Bedrock client target |
| `BEDROCK_PRIMARY_MODEL_ID` | parameter | Primary agent model — an EU inference profile id |
| `BEDROCK_SECONDARY_MODEL_ID` | parameter | Second model for side-by-side evaluation |
| `BEDROCK_SECONDARY_REGION` | parameter | Region for the secondary model when it differs from the primary's — the pilot's Mistral is in-region in `eu-west-1` ([`llm.md`](./llm.md)) |
| `FEEDBACK_TABLE` / `CONVERSATION_TABLE` | foundation stack | DynamoDB table names |
| `FEEDBACK_TTL_DAYS` / `CONVERSATION_TTL_DAYS` | foundation stack | Retention the backend must stamp into `expires_at` |
| `DATA_LAYER_BUCKET` | foundation stack | Bucket for GeoJSON/GeoParquet artifacts |
| `DATA_LAYER_PRESIGN_TTL` | parameter (3600) | Lifetime of presigned URLs handed to the browser |
| `PUBLIC_BASE_URL` | parameter | Public origin; emit same-origin data URLs against it |
| `ALLOWED_ORIGINS` | parameter | Accepted WebSocket origin (comma-separated; empty allows any, for local development) |
| `MCP_SERVER_URL` | parameter (empty) | MCP endpoint, and **the switch that enables the chat**. Empty means no production geodata server, so `/ws/v1` accepts connections and refuses every turn ([`protocol.md`](./protocol.md#waiting-for-the-production-mcp-server)). Set it to `http://sgs-llm-geosearch:8790/mcp` — the geosearch foundation stack's `McpServerUrl` output, together with `ServiceConnectNamespace` — to turn the chat on ([Geodata MCP server](#geodata-mcp-server-geosearch-deployment)) |
| `MCP_SERVER_TOKEN` | **Secrets Manager** `sgs-llm/backend` | MCP credential; never in git, never in CI logs |
| `API_KEY` | parameter (**empty**) | Optional shared key for `/ws/v1` and `/feedback`. Empty leaves them open, as [`protocol.md`](./protocol.md#limits-and-the-optional-key) describes - read that before enabling it, it is not a security boundary |
| `TURN_TIMEOUT_SECONDS` | parameter (90) | Wall-clock budget per turn, then `error` `timeout` |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | parameter (20) | Per-client allowance; every turn spends Bedrock tokens |
| `MAX_CONNECTIONS_PER_IP` | parameter (8) | Concurrent WebSocket connections per client |

Fill in a secret value out-of-band, then restart the service to pick it up:

```bash
aws secretsmanager put-secret-value --profile swisstopo --region eu-central-1 \
  --secret-id sgs-llm/backend \
  --secret-string '{"MCP_SERVER_TOKEN":"<value>"}'
aws ecs update-service --profile swisstopo --region eu-central-1 \
  --cluster sgs-llm --service sgs-llm-backend --force-new-deployment
```

### What gets stored

Two DynamoDB tables (on-demand billing, point-in-time recovery on, TTL enabled).
The GSI partition key is named `log_date` rather than `day` because **`DAY` is a
DynamoDB reserved word** and would otherwise need an expression-attribute alias in
every query.

**`sgs-llm-feedback`** — one item per submitted feedback form:

| Attribute | Role |
| --- | --- |
| `id` | partition key (uuid) |
| `log_date` + `ts` | `ByDay` GSI: `YYYY-MM-DD` + ISO-8601 timestamp, newest-first reads |
| `category` | `bug` \| `feature` \| `improvement` \| `question` \| `other` |
| `message`, `email?`, `lang` | as submitted by the form ([`submitFeedback.ts`](../frontend/src/feedback/submitFeedback.ts)) |
| `expires_at` | epoch seconds; DynamoDB TTL deletes the item (default 365 days) |

**`sgs-llm-conversations`** — one item per conversation turn:

| Attribute | Role |
| --- | --- |
| `conversation_id` | partition key |
| `turn` | sort key, `"<iso-timestamp>#<message_id>"` — one Query returns a conversation in order |
| `log_date` + `ts` | `ByDay` GSI |
| `message_id`, `lang` | the turn's protocol id and request language |
| `user_message`, `assistant_markdown` | the exchange as the user saw it |
| `model_id` | which model actually served the turn, e.g. `mistral.ministral-3-14b-instruct@eu-west-1` - the fallback means this is not fixed |
| `tool_calls`, `layer_count` | tool names in call order, and how many layers were returned |
| `latency_ms`, `input_tokens`, `output_tokens` | for evaluating cost and speed |
| `error_code` | present only on a failed turn: the protocol codes (`internal`, `timeout`, `cancelled`, `bad_request`), plus `mcp_not_configured` for a turn refused because no geodata server is connected - that one is not a protocol code, it is recorded so the dark period can be counted |
| `expires_at` | epoch seconds; TTL default 90 days |

Failed turns are recorded too - a turn that timed out is exactly the kind of thing the
pilot needs to count. Both writes are **best effort**: storage exists to evaluate the
pilot, so a DynamoDB failure is logged and swallowed rather than costing a user their
answer or making them retype their feedback.

Everything else (per-request operational logging) goes to the CloudWatch log
group `/ecs/sgs-llm-backend`, retention 30 days. One line per turn records the model,
tools, layer count, latency and error code, so the service can be watched with
`aws logs tail` without reading the tables.

> ⚠️ **Data protection.** Storing conversation turns and feedback (which may
> include an email address the user typed) is **personal data**, and it changes
> what [`architecture.md`](./architecture.md#security-notes) used to promise. The
> retention periods above are defaults chosen here, not an approved policy —
> **they need sign-off from swisstopo before this carries real user traffic**, and
> the privacy notice shown to users should match. Bedrock **model invocation
> logging is deliberately left off**: it would capture full prompts and responses,
> it is an account-wide per-region setting, and the application-level tables above
> already cover the requirement.

### Run the backend locally

No AWS profile needed beyond a Bedrock key - the same one
[`scripts/ask-llm.py`](../scripts/ask-llm.py) uses, so the VPN is required.

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

export AWS_BEARER_TOKEN_BEDROCK=<key>
export BEDROCK_SECONDARY_MODEL_ID=mistral.ministral-3-14b-instruct
export BEDROCK_SECONDARY_REGION=eu-west-1
# Leave BEDROCK_PRIMARY_MODEL_ID unset while Claude is blocked by the SCP: the backend
# then goes straight to the working model instead of failing over on every turn.

PYTHONPATH=..:. .venv/bin/python -m uvicorn app.main:app --port 8787 --reload
```

With no tables and no bucket configured it runs without AWS: artifacts are served from
memory at `/data/...` and persistence is disabled. The frontend's default `config.json`
already points at `localhost:8787`, so `cd frontend && npm run dev` needs no change.

**The chat needs an MCP server.** With `MCP_SERVER_URL` unset the backend refuses every
turn, exactly as the deployed pilot does. To develop against real geodata, run the
bundled stand-in in a third terminal and point the backend at it:

```bash
python -m mcp_dummy.server                       # http://127.0.0.1:8788/mcp
export MCP_SERVER_URL=http://127.0.0.1:8788/mcp  # then start the backend
```

Checks before pushing - the same ones CI runs:

```bash
cd backend
.venv/bin/python -m ruff check app tests ../mcp_dummy ../evals
.venv/bin/python -m ruff format --check app tests ../mcp_dummy ../evals
.venv/bin/python -m mypy          # app, mcp_dummy and evals (see pyproject.toml)
.venv/bin/python -m pytest
```

The gate that decides whether the image may deploy - build from the **repository root**,
which is the context CI and `scripts/deploy-backend.sh` use (`mcp_dummy/` is deliberately
not copied into the image):

```bash
cd ..
docker build -f backend/Dockerfile -t sgs-llm-backend:local .
docker run -d --name smoke -p 8787:8787 sgs-llm-backend:local
curl -sf http://127.0.0.1:8787/health
curl -s -o /dev/null -w '%{http_code}\n' --http1.1 \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  --max-time 5 http://127.0.0.1:8787/ws/v1            # → 101
docker rm -f smoke
```

### Deploy the backend code

**Automatic (default).** Pushing to `main` runs
[`.github/workflows/backend.yml`](../.github/workflows/backend.yml) when
`backend/**`, `mock-agent/**` or the deploy script changed — frontend-only commits
do not restart the service. The workflow builds the image, **smoke-tests it
locally** (health check plus a real `101 Switching Protocols` upgrade) before any
AWS call, then assumes
`arn:aws:iam::259789526488:role/github-actions-sgs-llm-backend-deploy` through
GitHub's OIDC provider — no stored AWS keys — and publishes:

```text
push to main → build image → smoke-test container → OIDC role
   → push to ECR (tagged with the commit sha)
   → register a new task definition revision pinned to that sha
   → ecs update-service → wait services-stable
```

Deploys are immutable: each one is its own task definition revision, so rolling
back is pointing the service at the previous one. The role is trusted only for
`repo:swisstopo/sgs-llm:ref:refs/heads/main` and can do nothing beyond ECR push on
the one repository and rolling the one service.

**Manual (fallback).**

```bash
PROFILE=swisstopo ./scripts/deploy-backend.sh          # build, push, roll, wait
BUILD_ONLY=1 PROFILE=swisstopo ./scripts/deploy-backend.sh   # publish the image only
```

The script prints the exact rollback command for the revision it replaced. If the
new task never becomes healthy, the circuit breaker rolls back and the script
exits non-zero.

### Inspect what the backend stored

[`scripts/read-db.sh`](../scripts/read-db.sh) reads both tables and prints JSONL
with DynamoDB's type wrappers removed, so it pipes into `jq`, `grep` or a file. It
only ever calls `Query` / `Scan` / `DescribeTable`.

```bash
PROFILE=sgs-llm-dev ./scripts/read-db.sh counts
PROFILE=sgs-llm-dev ./scripts/read-db.sh feedback                      # last 7 days
PROFILE=sgs-llm-dev ./scripts/read-db.sh feedback --day 2026-07-29
PROFILE=sgs-llm-dev ./scripts/read-db.sh conversations --conversation <id>
PROFILE=sgs-llm-dev ./scripts/read-db.sh feedback | jq -r '.category' | sort | uniq -c
```

### Use the models from a workstation

The `sgs-llm-dev` role grants **Bedrock inference on the pilot's EU profiles** and
**read-only access to the two tables** — enough to try prompts, compare models and
read what the backend stored, with no long-lived access key anywhere. Every
statement in it is conditioned on `aws:SourceIp`, so it works from the fixed office
address only (kept out of this repository — see
[`infra/dev-access.env.example`](../infra/dev-access.env.example)).

Add a profile that assumes it (`~/.aws/config`, structure only — no secrets):

```ini
[profile sgs-llm-dev]
role_arn = arn:aws:iam::259789526488:role/sgs-llm-dev
source_profile = swisstopo
region = eu-central-1
```

```bash
# What can this account actually call?
aws bedrock list-inference-profiles --profile sgs-llm-dev --region eu-central-1 \
  --type SYSTEM_DEFINED --query 'inferenceProfileSummaries[].inferenceProfileId'

# One turn against the primary model.
aws bedrock-runtime converse --profile sgs-llm-dev --region eu-central-1 \
  --model-id eu.anthropic.claude-sonnet-4-6 \
  --messages '[{"role":"user","content":[{"text":"Nenne drei Schweizer Kantone."}]}]' \
  --query 'output.message.content[0].text' --output text
```

> The IP condition applies to direct API calls, which is what the CLI and SDKs
> make. Requests the **AWS console** issues on your behalf may not present your
> browser address, so use this role from the CLI/SDK and browse the console with
> your normal IAM Identity Center role instead.

**Model access without any AWS profile — Bedrock API key.** For developers who
only need to call the models, the IAM user `sgs-llm-bedrock-key` carries a
long-term Bedrock API key (a bearer token). It permits `bedrock:InvokeModel*`
only, and only from the fixed developer network; simulated from any other
address every action is denied, and even on-network it cannot touch DynamoDB,
S3 or anything else. Usage is one environment variable:

```bash
export AWS_BEARER_TOKEN_BEDROCK=<key>          # from the project admin
python scripts/ask-llm.py "Nenne drei Schweizer Kantone."
```

Rotate or revoke it with
`aws iam list-service-specific-credentials --user-name sgs-llm-bedrock-key` and
`aws iam delete-service-specific-credential --user-name sgs-llm-bedrock-key
--service-specific-credential-id <id>`; a new one is
`aws iam create-service-specific-credential --user-name sgs-llm-bedrock-key
--service-name bedrock.amazonaws.com`. The key value itself is never stored in
this repository.

### Bedrock model access

Model access is an account-level, per-region setting; the roles above grant the
API permission but not the entitlement.

```bash
# What exists in this region, and under which id?
aws bedrock list-inference-profiles --profile swisstopo --region eu-central-1 \
  --type SYSTEM_DEFINED --query 'inferenceProfileSummaries[].[inferenceProfileId,status]' --output table
aws bedrock list-foundation-models --profile swisstopo --region eu-central-1 \
  --query 'modelSummaries[?contains(modelId,`anthropic`)||contains(modelId,`mistral`)].modelId'

# Which regions does an EU profile actually route to?
aws bedrock get-inference-profile --profile swisstopo --region eu-central-1 \
  --inference-profile-identifier eu.anthropic.claude-sonnet-4-6
```

Enable access for the pilot models in the Bedrock console ("Model access") and
then **prove it with a real call** (the `converse` example above): an EU profile
can return `AccessDeniedException` until the models are enabled for the regions the
profile routes to. Check the on-demand tokens-per-minute quotas in Service Quotas
for the models in use and request increases early — they are not instant.

### Cut CloudFront over to the backend

The distribution's `/ws/v1`, `/feedback` and `/data/*` behaviors already carry the
right cache/origin-request policies and allowed methods
([appendix](#appendix-cloudfront-distribution-config)); only the origin's
`DomainName` changes, from the EC2 public DNS to the ALB DNS name. Keep
`OriginProtocolPolicy: http-only` and the `X-Forwarded-Proto: https` custom header
— the backend derives its public URLs from those, exactly as the mock-agent does
on EC2.

```bash
ALB=$(aws cloudformation describe-stacks --profile swisstopo --region eu-central-1 \
  --stack-name sgs-llm-backend-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" --output text)

aws cloudfront get-distribution-config --id E2AEIO5QX64WCY --profile swisstopo \
  > /tmp/dist.json                       # contains the config and its ETag
# Add the ALB as a SECOND origin (`alb-agent`, HTTPPort 80) and repoint the three
# agent behaviors' TargetOriginId to it. Keep the `ec2-agent` origin in place.
aws cloudfront update-distribution --id E2AEIO5QX64WCY --profile swisstopo \
  --distribution-config file:///tmp/dist-config.json --if-match <ETag>
aws cloudfront wait distribution-deployed --id E2AEIO5QX64WCY --profile swisstopo
```

Keeping the old origin is deliberate: **rollback is flipping three
`TargetOriginId` values back to `ec2-agent`**, with no origin to recreate. The
distribution now carries both (`ec2-agent` → EC2, `alb-agent` → ALB, port 80).

Re-run the [verification block](#6-verify) afterwards — including the WebSocket
`101` check — then the browser demo script. Because the mock-agent is also the
bootstrap container image, the demo behaves identically before and after the
cutover; the EC2 instance can then be **stopped but kept** as a rollback origin.

Done on 2026-07-29: all three behaviors serve from Fargate (`site 200`,
`deeplink 200`, `data 200`, `feedback 204`, WebSocket `101 Switching Protocols`),
and a direct request to the ALB from the public internet times out.

### Operate the backend

```bash
P=(--profile swisstopo --region eu-central-1)

# Is it healthy?
aws ecs describe-services "${P[@]}" --cluster sgs-llm --services sgs-llm-backend \
  --query 'services[0].{desired:desiredCount,running:runningCount,taskDef:taskDefinition}'
aws elbv2 describe-target-health "${P[@]}" --target-group-arn <TargetGroupArn> \
  --query 'TargetHealthDescriptions[].TargetHealth.State'

# Logs (application + startup failures)
aws logs tail /ecs/sgs-llm-backend "${P[@]}" --since 30m --follow

# Why did a deploy fail?
aws ecs describe-services "${P[@]}" --cluster sgs-llm --services sgs-llm-backend \
  --query 'services[0].events[:5].message'

# Shell into the running task (ECS Exec is enabled)
TASK=$(aws ecs list-tasks "${P[@]}" --cluster sgs-llm --service-name sgs-llm-backend \
  --query 'taskArns[0]' --output text)
aws ecs execute-command "${P[@]}" --cluster sgs-llm --task "$TASK" \
  --container sgs-llm-backend --interactive --command "/bin/sh"

# Park it (stops Fargate charges; the ALB and CloudFront stay up and 503 the chat)
aws ecs update-service "${P[@]}" --cluster sgs-llm --service sgs-llm-backend --desired-count 0
aws ecs update-service "${P[@]}" --cluster sgs-llm --service sgs-llm-backend --desired-count 1

# Restart on the same image (e.g. after changing a secret)
aws ecs update-service "${P[@]}" --cluster sgs-llm --service sgs-llm-backend --force-new-deployment

# Roll back to a specific revision
aws ecs update-service "${P[@]}" --cluster sgs-llm --service sgs-llm-backend \
  --task-definition sgs-llm-backend:<revision>
```

### Backend cost

Approximate, at pilot scale in eu-central-1, excluding Bedrock usage:

| Item | ~ per month |
| --- | --- |
| Fargate 4 vCPU / 8 GB, 1 task, 24/7 | ~$165 |
| Application Load Balancer | ~$20 + LCU |
| NAT gateway | **$0** — cannot be created in this account, so egress uses the subnets' internet gateway |
| ECR, DynamoDB on-demand, CloudWatch, Secrets Manager | a few dollars |
| **Total** | **~$190** |

Fargate is the dominant cost and scales with the task size, so
`--desired-count 0` between demos is the effective lever; dropping to 1 vCPU / 2 GB
saves ~$125/month if the headroom proves unnecessary. Bedrock is billed per token
on top.

### Backend teardown

```bash
P=(--profile swisstopo --region eu-central-1)
aws cloudformation delete-stack "${P[@]}" --stack-name sgs-llm-backend-service
aws cloudformation wait stack-delete-complete "${P[@]}" --stack-name sgs-llm-backend-service
aws cloudformation delete-stack "${P[@]}" --stack-name sgs-llm-backend-foundation
aws cloudformation wait stack-delete-complete "${P[@]}" --stack-name sgs-llm-backend-foundation

# Retained on purpose — delete only if the stored user data is really finished with:
aws s3 rm s3://sgs-llm-data-259789526488 --recursive "${P[@]}"
aws s3api delete-bucket --bucket sgs-llm-data-259789526488 "${P[@]}"
aws dynamodb delete-table --table-name sgs-llm-feedback "${P[@]}"
aws dynamodb delete-table --table-name sgs-llm-conversations "${P[@]}"
```

Repoint the CloudFront agent behaviors back at the EC2 origin first, or the chat
path 502s.

### Region

Frankfurt (`eu-central-1`) as today. Claude is reached through the Bedrock **EU
inference profile** regardless of the task's region (it is not hosted in-region
in Frankfurt or Zurich), so the model is available without enabling Zurich.
Enable **eu-central-2 (Zurich)** for the compute/data path if in-country Swiss
residency is later required — Bedrock is available there too.

## Geodata MCP server (geosearch) deployment

The geodata tools the backend calls over MCP are served by **`geosearch`**, a second
container in this repository ([`geosearch/`](../geosearch/)). It runs as a **second ECS
Fargate service in the same `sgs-llm` cluster** as the backend, with **no load balancer**:
the backend reaches it over ECS Service Connect at

```text
http://sgs-llm-geosearch:8790/mcp
```

Its internal design (the FAISS index, the rerank stage, the `result_id` handles) is in
[`geosearch/README.md`](../geosearch/README.md).

```text
        ECS cluster `sgs-llm`  (one cluster, two services)
        ┌──────────────────────────────────────────────────────────────────┐
 ALB ──▶│  service sgs-llm-backend      4 vCPU / 8 GB   task SG: from ALB   │
        │        │                                                          │
        │        │  MCP over HTTP, Service Connect, VPC-internal only       │
        │        ▼                                                          │
        │  service sgs-llm-geosearch    2 vCPU / 4 GB   task SG: from backend SG
        │        image carries: FAISS index + 6272 boundaries               │
        └────────┬──────────────────────────────┬──────────────────────────┘
                 │                              │
                 ▼                              ▼
        api3.geo.admin.ch              Bedrock (rerank, eu-west-1)
        (features at query time)       S3 sgs-llm-data-* (published layers)
```

### Why the same cluster

**We do not create a new cluster.**
[`infra/geosearch-service.yaml`](../infra/geosearch-service.yaml) takes `ClusterName` as a
plain string parameter and references the cluster that
[`infra/backend-service.yaml`](../infra/backend-service.yaml) creates. Two stacks cannot
both own one cluster, so exactly one does.

The reason is that **on Fargate a cluster is a namespace, not a machine.** It owns no
capacity, has no size, and costs nothing; billing is per task vCPU-second and GB-second,
identically either way. A second cluster would therefore buy no isolation and no
capacity — it would only split the metrics, the `ecs execute-command` invocations and the
operator's attention across two names.

What actually isolates the two services is what *is* separate: their own task definitions,
task roles, security groups, log groups, ECR repositories, CI deploy roles and
CloudFormation stacks. A geosearch deploy cannot touch the backend service, and the
geosearch task role cannot read the conversation tables.

> This flips if the launch type ever changes. On **EC2** capacity a cluster owns real
> instances, and you would not want geosearch's index-loading container scheduled onto
> the same instances as the backend. On Fargate there are no instances to share.

### Three ways this differs from the backend

| | Backend | Geosearch | Why |
| --- | --- | --- | --- |
| Ingress | ALB, from CloudFront | **None** — Service Connect | The only client is a task in the same VPC. The browser never speaks MCP; it only fetches the presigned S3 URL a tool returns. Saves the ALB's ~$20/month and leaves no public path to it |
| Scale | desired 1, raisable | desired 1, **`MaxValue: 1`** | `result_id` handles live in the `ResultCache` inside one process ([`geosearch/results.py`](../geosearch/results.py)). A second task answers `compute` with "unknown result_id" for half the handles it just issued |
| Deploy | 100/200 rolling, zero downtime | **0/100** — old task stops first | Same reason. The cost is a gap of a minute or two per deploy, during which the backend's tool calls fail. Raising either needs a shared result store or sticky routing first |

### The index is built by a human, not by CI

The image needs a prebuilt search index, and **the build must never run in the Dockerfile
or in CI**: `python -m geosearch.build` takes ~12 minutes, makes a few thousand requests to
`geo.admin.ch`, and two runs a week apart produce two different indexes — the opposite of a
reproducible image.

```text
  workstation                     S3                        CI                    ECS
  python -m geosearch.build  ──▶  sgs-llm-index-*/index  ──▶  docker build  ──▶  service
  (~12 min, once per refresh)     (versioned, no expiry)     (copies it in)      (rolls)
```

What ends up inside the image:

| Baked in | Size | Rebuilt when |
| --- | --- | --- |
| DuckDB rows + three `.faiss` files | ~36 MB | a human runs `geosearch.build` |
| 6272 division boundaries (GeoJSON) | ~108 MB | same |
| **Layer catalogue and feature data** | — | **not baked** — fetched from `geo.admin.ch` per request |

That last row matters: a six-month-old image still queries today's data. Only the
*searchable set of layers* is as of the build.

There used to be a third row here — 2.1 GB of e5-large ONNX weights, baked by a `RUN` step
so that a cold start did not download them. Embedding is a Bedrock call to
`eu.cohere.embed-v4:0` now, so the weights, the `RUN` step and ~4.3 GB of image are gone.

Row `rid` in DuckDB is vector `rid` in the `.faiss` files, and `GeoIndex` refuses to load
against a different embedding model, so the index and the code ship together or not at all.
The Dockerfile still constructs `GeoIndex` at build time, now purely as a check: it opens
DuckDB, reads the three `.faiss` files and asserts their vector counts match the row
counts, so a truncated `COPY` fails in CI rather than in the cluster.

### Infrastructure: two more CloudFormation stacks

| Stack | Template | Contents |
| --- | --- | --- |
| `sgs-llm-geosearch-foundation` | [`infra/geosearch-foundation.yaml`](../infra/geosearch-foundation.yaml) | ECR repository, the index bucket, Cloud Map namespace + discovery service, log group, task security group, task/execution roles, CI deploy role. Consumes the backend foundation's VPC, subnets, task security group and data-layer bucket; creates no network topology |
| `sgs-llm-geosearch-service` | [`infra/geosearch-service.yaml`](../infra/geosearch-service.yaml) | Task definition and the Fargate service. **References the existing cluster; does not create one** |

Split for the same reason the backend's is: an ECS service cannot be created before an
image exists in ECR, and ECR is itself infrastructure.

The index bucket is versioned with **no object expiry**, unlike `sgs-llm-data-*` — whose
`expire-data-layers` rule deletes everything after 30 days. That rule is correct for
published layers and fatal for a search index, which is why the two are separate buckets
and why the division boundaries ship inside the image rather than in either one.

#### Deploy the infrastructure

Order matters: the backend's foundation and service stacks must exist first (the foundation
exports the VPC wiring; the service creates the cluster).

```bash
PROFILE=swisstopo
REGION=eu-central-1

aws cloudformation deploy --profile "$PROFILE" --region "$REGION" \
  --stack-name sgs-llm-geosearch-foundation \
  --template-file infra/geosearch-foundation.yaml \
  --capabilities CAPABILITY_NAMED_IAM

# Build and publish the index — ~12 minutes, from a machine with network access and
# AWS credentials (embedding is a Bedrock call).
python -m geosearch.build
INDEX_URI=$(aws cloudformation describe-stacks --profile "$PROFILE" --region "$REGION" \
  --stack-name sgs-llm-geosearch-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='IndexUri'].OutputValue" --output text)
aws s3 sync index/ "$INDEX_URI/" --delete --profile "$PROFILE" --region "$REGION"

# First image, so the service stack has something to start. BUILD_ONLY skips the
# ECS roll, which cannot work yet because the service does not exist.
BUILD_ONLY=1 USE_LOCAL_INDEX=1 PROFILE=$PROFILE ./scripts/deploy-geosearch.sh

aws cloudformation deploy --profile "$PROFILE" --region "$REGION" \
  --stack-name sgs-llm-geosearch-service \
  --template-file infra/geosearch-service.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

Then set the repository variable **`GEOSEARCH_INDEX_URI`** to that `IndexUri` so CI can
build the image.

**Do this before merging geosearch to `main`.** Until it is set,
`.github/workflows/geosearch.yml` runs the tests and then **fails the deploy job**. That is
deliberate: the job cannot build an image without an index, and a green run that built and
shipped nothing reads as a successful deploy to everyone who sees only the tick. The same
job also fails if the sync finds no DuckDB file, no `.faiss` vectors or no boundaries under
`s3/` — `aws s3 sync` exits 0 against an empty prefix, so the files are the check, not the
transfer.

#### Turn the chat on

The backend refuses every turn while `MCP_SERVER_URL` is empty. Point it at the geosearch
foundation stack's `McpServerUrl` output — a template parameter, so **no image rebuild**:

```bash
PROFILE=swisstopo ./scripts/deploy-backend-stack.sh \
  McpServerUrl=http://sgs-llm-geosearch:8790/mcp \
  ServiceConnectNamespace=arn:aws:servicediscovery:eu-central-1:259789526488:namespace/ns-5w75umkx6cpbo456
```

Both parameters, not just the first. `sgs-llm-geosearch` is a Service Connect name, and a
task that has not joined the namespace cannot resolve it — set `McpServerUrl` alone and
every tool call fails with a DNS error instead of the clean refusal. The ARN is the
geosearch foundation stack's `NamespaceArn` output.

Use [`deploy-backend-stack.sh`](../scripts/deploy-backend-stack.sh), not a bare
`aws cloudformation deploy`: the latter blanks the `NoEcho` `ApiKey` parameter.

The template default stays empty on purpose. An unreachable URL would make every turn fail
with a connection error instead of the clean "no geodata server" refusal
([`protocol.md`](./protocol.md#waiting-for-the-production-mcp-server)), so the switch is
thrown once geosearch is actually running.

#### Environment contract

| Variable | Source | Meaning |
| --- | --- | --- |
| `PORT` | parameter (8790) | Must match the security group rule and the DNS record |
| `GEOSEARCH_S3_BUCKET` | backend foundation stack | Where published layers go. **Setting it is what switches the server from the local moto stand-in to real S3** (`geosearch/server.py:_artifact_store`), so it must always be present here |
| `GEOSEARCH_S3_REGION` | stack region | — |
| `BEDROCK_SECONDARY_MODEL_ID` | parameter (`mistral.ministral-3-14b-instruct`) | Reranks the FAISS candidates. Small on purpose — a filter, not a writer, and it runs on every search |
| `BEDROCK_SECONDARY_REGION` | parameter (`eu-west-1`) | In-region on-demand is the one path the organization SCP does not block ([`llm.md`](./llm.md)) |
| `GEOSEARCH_EMBED_REGION` | default (`eu-central-1`) | Where `eu.cohere.embed-v4:0` is invoked. The task role's `bedrock-rerank` policy is scoped to `eu-*` inference profiles, so this must stay in the EU |
| `LOG_LEVEL` | parameter (`info`) | — |

There is no `MCP_SERVER_TOKEN` equivalent: the server has no auth, because its security
group admits only the backend's security group. That is the boundary — do not put it behind
a public endpoint without adding one.

#### Deploy the code

Pushing changes under `geosearch/` to `main` runs
[`.github/workflows/geosearch.yml`](../.github/workflows/geosearch.yml): ruff and the
geosearch tests always, then (if `GEOSEARCH_INDEX_URI` is set, and never on a pull request,
which must not reach the AWS role) fetch the index, build, smoke-test `/health` in a
container, and call the same script a human would:

```bash
PROFILE=swisstopo ./scripts/deploy-geosearch.sh
```

Deploys are immutable — the image is tagged with the commit sha and a **new task definition
revision** is registered, so a rollback is pointing the service at the previous revision
(the script prints the exact command). The circuit breaker rolls back automatically if the
new task never becomes healthy, and the script then fails the job.

`USE_LOCAL_INDEX=1` builds from `./index` as it stands instead of fetching; `BUILD_ONLY=1`
publishes the image without touching the service.

#### Health checks

`streamable_http_app` serves `/mcp` and nothing else, and `/mcp` cannot answer a plain GET,
so the server adds **`/health`** beside it — returning the index counts, not just `ok`:

```json
{"status": "ok", "layers": 896, "divisions": 6272}
```

With no load balancer, the **container** health check is what decides whether the task's IP
is registered in the Service Connect namespace at all, so a task that started without an
index never receives traffic. It is declared in both the Dockerfile and the task
definition; ECS reads the task definition's. `StartPeriod` is 120 s to cover reading the
index off local disk and opening DuckDB.

#### Operate geosearch

```bash
P=(--profile swisstopo --region eu-central-1)

# Is it healthy, and is DNS pointing at it?
aws ecs describe-services "${P[@]}" --cluster sgs-llm --services sgs-llm-geosearch \
  --query 'services[0].{desired:desiredCount,running:runningCount,taskDef:taskDefinition}'
aws servicediscovery discover-instances "${P[@]}" \
  --namespace-name sgs-llm --service-name sgs-llm-geosearch

aws logs tail /ecs/sgs-llm-geosearch "${P[@]}" --since 30m --follow

# Reach /health from inside (there is no public path, by design)
TASK=$(aws ecs list-tasks "${P[@]}" --cluster sgs-llm --service-name sgs-llm-geosearch \
  --query 'taskArns[0]' --output text)
aws ecs execute-command "${P[@]}" --cluster sgs-llm --task "$TASK" \
  --container sgs-llm-geosearch --interactive \
  --command "python -c \"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8790/health').read())\""

# Park it (the backend then fails every turn — it is not optional for the chat)
aws ecs update-service "${P[@]}" --cluster sgs-llm --service sgs-llm-geosearch --desired-count 0
```

#### Geosearch cost

Approximate, on top of the backend's ~$190, excluding Bedrock usage:

| Item | ~ per month |
| --- | --- |
| Fargate 2 vCPU / 4 GB, 1 task, 24/7 | ~$83 |
| Load balancer | **$0** — there isn't one |
| Cloud Map namespace | **$0** — an HTTP namespace creates no hosted zone |
| ECR (last 5 images kept, ~0.5 GB each), index bucket (~143 MB), CloudWatch | a few dollars |
| **Total** | **~$90** |

Fargate again dominates, so `--desired-count 0` between demos is the lever. Since embedding
moved to Bedrock, a request is almost entirely waiting — on Bedrock, then on
`geo.admin.ch` — so neither CPU nor memory is under pressure. What still holds memory is
`filter_features`, which keeps a whole layer's geometry in RAM while clipping it; that is
why this is 4 GB and not less.

#### Geosearch teardown

```bash
P=(--profile swisstopo --region eu-central-1)
aws cloudformation delete-stack "${P[@]}" --stack-name sgs-llm-geosearch-service
aws cloudformation wait stack-delete-complete "${P[@]}" --stack-name sgs-llm-geosearch-service
aws cloudformation delete-stack "${P[@]}" --stack-name sgs-llm-geosearch-foundation
aws cloudformation wait stack-delete-complete "${P[@]}" --stack-name sgs-llm-geosearch-foundation

# Retained on purpose — deleting it means a 25-minute rebuild to get back:
aws s3 rm s3://sgs-llm-index-259789526488 --recursive "${P[@]}"
aws s3api delete-bucket --bucket sgs-llm-index-259789526488 "${P[@]}"
```

Set the backend's `McpServerUrl` back to `''` first, or the chat fails every turn on a
connection error instead of refusing cleanly. The backend stacks and the cluster are
unaffected — the cluster belongs to `sgs-llm-backend-service`.

## Follow-ups (post-POC)

- **Data-protection sign-off** for storing conversation turns and feedback emails,
  and a privacy notice that matches the retention actually configured — see
  [What gets stored](#what-gets-stored). Blocking for real user traffic.
- Move to **eu-central-2 (Zurich)** once the region is enabled.
- **Terminate the EC2 mock-agent** once the Fargate backend has run a while (it is
  kept stopped as a rollback origin in the meantime).
- **Scale the backend out** — raise the ECS desired count and enable autoscaling
  (on CPU or ALB connection count) once past the single pilot task.
- **Load-test the backend** — drive concurrent WebSocket chat sessions to size
  the task (CPU/memory), the autoscaling thresholds, and the ALB idle timeout
  before production traffic.
- **Second NAT gateway** (one per AZ) when egress becomes availability-critical.
- **Custom domain** + ACM certificate.
- **Scale geosearch past one task** — needs a shared `result_id` store (or sticky
  routing) first; until then `DesiredCount` is capped at 1 and every deploy takes a
  short outage. See [Three ways this differs from the backend](#three-ways-this-differs-from-the-backend).
- **Automate the index refresh** — `python -m geosearch.build` is a manual ~25-minute
  step today; a scheduled job that builds, publishes and opens a PR would keep the
  searchable layer set current without a human.

Done since the initial POC: ✔ GitHub Actions deploy on push to `main` (OIDC
role, no static keys — see step 7 and "Redeploy the frontend"); ✔ agent backend on
ECS Fargate + ALB with keyless CI deploys, persistence for feedback and
conversation logs, and IP-scoped developer access to the models and the tables
(see [Backend deployment](#backend-deployment)); ✔ the geodata MCP server as a
second Fargate service in the same cluster, with its own stacks, index bucket and
keyless CI deploys (see [Geodata MCP server](#geodata-mcp-server-geosearch-deployment)).

## Appendix: CloudFront distribution config

`cf-dist.json` used for this deployment. Replace the S3 regional domain
(`<BUCKET>.s3.<REGION>.amazonaws.com`), the `OriginAccessControlId`, and the
`ec2-agent` `DomainName` (the EC2 public DNS) for a fresh deploy. Managed policy
IDs are global constants: CachingOptimized `658327ea-f89d-4fab-a63d-7e88639e58f6`,
CachingDisabled `4135ea2d-6df8-44a3-9df3-4b5a84be39ad`, AllViewer origin-request
`216adef6-5c7f-47e4-b989-5492eafa07d3`.

```json
{
  "CallerReference": "sgs-llm-poc-frontend-001",
  "Comment": "SGS LLM POC - frontend (S3) + mock-agent (EC2)",
  "Enabled": true,
  "DefaultRootObject": "index.html",
  "HttpVersion": "http2and3",
  "IsIPV6Enabled": true,
  "PriceClass": "PriceClass_100",
  "Origins": {
    "Quantity": 2,
    "Items": [
      {
        "Id": "s3-frontend",
        "DomainName": "sgs-llm-frontend-259789526488.s3.eu-central-1.amazonaws.com",
        "OriginAccessControlId": "E3NND1A7M7LYCH",
        "S3OriginConfig": { "OriginAccessIdentity": "" }
      },
      {
        "Id": "ec2-agent",
        "DomainName": "<EC2_PUBLIC_DNS>",
        "CustomOriginConfig": {
          "HTTPPort": 8787,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only",
          "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] },
          "OriginReadTimeout": 60,
          "OriginKeepaliveTimeout": 60
        },
        "CustomHeaders": {
          "Quantity": 1,
          "Items": [ { "HeaderName": "X-Forwarded-Proto", "HeaderValue": "https" } ]
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "s3-frontend",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": { "Quantity": 2, "Items": ["GET","HEAD"], "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] } },
    "Compress": true,
    "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6"
  },
  "CacheBehaviors": {
    "Quantity": 3,
    "Items": [
      {
        "PathPattern": "/ws/v1",
        "TargetOriginId": "ec2-agent",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": { "Quantity": 7, "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"], "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] } },
        "Compress": false,
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3"
      },
      {
        "PathPattern": "/feedback",
        "TargetOriginId": "ec2-agent",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": { "Quantity": 7, "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"], "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] } },
        "Compress": false,
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3"
      },
      {
        "PathPattern": "/data/*",
        "TargetOriginId": "ec2-agent",
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": { "Quantity": 3, "Items": ["GET","HEAD","OPTIONS"], "CachedMethods": { "Quantity": 2, "Items": ["GET","HEAD"] } },
        "Compress": true,
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3"
      }
    ]
  },
  "CustomErrorResponses": {
    "Quantity": 2,
    "Items": [
      { "ErrorCode": 403, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0 },
      { "ErrorCode": 404, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0 }
    ]
  },
  "ViewerCertificate": { "CloudFrontDefaultCertificate": true }
}
```
