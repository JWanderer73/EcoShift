# Next.js dashboard for ECS Fargate. Build from this folder:
#   docker build -t carbon-windows-web frontend/
# NEXT_PUBLIC_* values are baked in at build time.
FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_ECOSHIFT_API_MODE=carbon-v1
# Only for docker compose: forwards /v1/* to the API container. On AWS the load balancer does this.
ARG API_PROXY_URL=
ENV NEXT_PUBLIC_ECOSHIFT_API_MODE=$NEXT_PUBLIC_ECOSHIFT_API_MODE \
    API_PROXY_URL=$API_PROXY_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=8501 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 8501
USER node
CMD ["node", "server.js"]
