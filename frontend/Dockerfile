# Build from the repository root (the curated layer catalog lives there):
#   docker build -f frontend/Dockerfile -t sgs-llm-frontend .
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY layers/ ./layers/
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
