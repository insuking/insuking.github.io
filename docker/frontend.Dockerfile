FROM node:22-slim AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend .

# Vite bakes VITE_* vars into the built JS at build time, not read at
# container start - so the API origin the built app talks to must be known
# here. Defaults to the existing local-dev value; docker-compose.yml passes
# a real public API origin (e.g. the Cloudflare Tunnel hostname, P43) as a
# build arg once one exists - see docs/ANDROID_APP.md.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:22-slim

WORKDIR /app
RUN npm install -g serve

COPY --from=build /app/dist ./dist

EXPOSE 5173

CMD ["serve", "-s", "dist", "-l", "5173"]
