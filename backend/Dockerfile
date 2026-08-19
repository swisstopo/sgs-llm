# The agent backend image - the only contract between this code and the deployed
# infrastructure (docs/deployment.md#what-the-container-image-must-provide):
# listens on $PORT, serves GET /health, WebSocket /ws/v1 and POST /feedback, handles
# SIGTERM, and is linux/amd64.
#
# Build from the repository root, which is what CI and scripts/deploy-backend.sh do:
#   docker build -f backend/Dockerfile -t sgs-llm-backend .
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so a code change does not reinstall them.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# mcp_dummy/ is deliberately NOT copied: the stand-in geodata server is a development and
# evaluation tool and must not ship to production.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8787 \
    ADMIN_USER_DB_PATH=/var/lib/sgs-llm/admin-users.sqlite3

RUN useradd --create-home --uid 10001 sgs \
    && install -d -o sgs -g sgs /var/lib/sgs-llm
USER sgs

EXPOSE 8787

# No curl in the slim image, and the check must stay dependency-free: /health
# deliberately touches neither Bedrock nor DynamoDB.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8787')+'/health').read()"]

# `exec` makes uvicorn PID 1, so it receives ECS's SIGTERM directly and drains its
# WebSocket connections within the 30 s stop timeout instead of being killed.
# ws-ping keeps quiet chats alive under the ALB's 3600 s idle timeout.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787} --log-level ${LOG_LEVEL:-info} --ws-ping-interval 20 --ws-ping-timeout 20 --timeout-graceful-shutdown 25"]
