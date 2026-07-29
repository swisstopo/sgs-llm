# Bootstrap image for the agent-backend ECS service (docs/deployment.md#backend-deployment).
#
# The mock-agent is the *reference* implementation of protocol v1, so running it
# on ECS proves the whole CloudFront -> ALB -> Fargate path (including the
# WebSocket upgrade) before the real backend exists. Once backend/Dockerfile
# lands, the deploy workflow builds that instead and nothing else changes.
#
# Build from the repository root:
#   docker build -f mock-agent/Dockerfile -t sgs-llm-backend .
FROM node:22-alpine

WORKDIR /app
COPY mock-agent/package.json mock-agent/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY mock-agent/ ./

ENV NODE_ENV=production \
    PORT=8787 \
    FEEDBACK_LOG=/tmp/feedback.log

# Run unprivileged (the node image ships a `node` user); /tmp stays writable.
USER node
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||8787)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# server.mjs installs its own SIGTERM/SIGINT handlers, so it drains correctly as
# PID 1 without an init shim.
CMD ["node", "server.mjs"]
