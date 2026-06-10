# Deployment (POC, AWS)

This document describes how the SGS LLM prototype is deployed to AWS, and how to
reproduce, redeploy, operate, and tear it down. It contains **no credentials** —
where credentials are needed, only the file *structure* is shown.

**Live URL:** https://denpw8uo5zpkl.cloudfront.net/

The frontend is a static single-page app on **S3 + CloudFront**; the development
**mock-agent** runs on a single **EC2** instance behind the *same* CloudFront
distribution. One HTTPS domain serves everything, so the browser only ever talks
to a single TLS origin — no mixed-content, no CORS, and `wss://` works.

```
                 ┌──────────────── CloudFront (HTTPS / wss, *.cloudfront.net) ──────────────┐
 browser ──────▶ │  default behavior            ── S3 origin (private, OAC) → dist/ + config.json │
 (https + wss)   │  /ws/v1, /feedback, /data/*  ── EC2 origin (http :8787)  → mock-agent          │
                 └────────────────────────────────────────────────────────────────────────────┘
```

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

## Region note

Deployed in **eu-central-1 (Frankfurt)**. The originally intended
**eu-central-2 (Zurich)** is an *opt-in* region and is currently **DISABLED** on
the account: regional calls there fail with `InvalidToken` / `AuthFailure` until
the region is enabled (`aws account enable-region --region-name eu-central-2`)
and activation completes. For the POC the only data in play is public
geo.admin.ch tiles and mock demo data, so Frankfurt is acceptable. Enable Zurich
for the production system.

## Resource inventory (current deployment)

| Resource | ID / value |
| --- | --- |
| Account / region | `259789526488` / `eu-central-1` |
| S3 bucket (private) | `sgs-llm-frontend-259789526488` |
| CloudFront distribution | `E2AEIO5QX64WCY` → `denpw8uo5zpkl.cloudfront.net` |
| CloudFront OAC | `E3NND1A7M7LYCH` |
| EC2 instance (`t3.small`, AL2023) | `i-08d1b778054ff9fdf` |
| Security group | `sg-028f6864ebde6e4b8` — TCP 8787 from the CloudFront managed prefix list only |

Everything is tagged `project=sgs-llm-poc`.

## Prerequisites

- **AWS CLI v2**, **GitHub CLI** (`gh`), **Node.js 22**.
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
```

## Follow-ups (post-POC)

- Move to **eu-central-2 (Zurich)** once the region is enabled.
- Give the agent a stable endpoint (**Elastic IP**, or replace the EC2 with a
  managed/serverless backend — ECS Fargate, or API Gateway WebSocket + Lambda)
  and swap the mock-agent for the real agent.
- **GitHub Actions** deploy on merge to `main` (OIDC role — no static keys).
- **Custom domain** + ACM certificate.

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
