# syntax=docker/dockerfile:1
#
# GIS Core Service web client (React + MapLibre).
#
# Targets:
#   dev    Vite dev server with hot reload (used by docker-compose.yml)
#   build  Production bundle in /app/dist, to be served by the platform ingress or CDN
#
# Build from the repository root:
#   docker build -f docker/frontend.Dockerfile --target build -t gis-core-service-web-build .

ARG NODE_IMAGE=node:24-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM deps AS dev
COPY frontend/ ./
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]

FROM deps AS build
COPY frontend/ ./
RUN npm run build
