# The web image: the React screens, built with Node and served by nginx, which also
# passes /api to the app container (docker/nginx.conf). Build from the repository root:
#   docker build -f docker/web.Dockerfile -t negativespace-web .
# Both images pinned by digest; update deliberately, rebuild and run CI.
FROM node:22-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS build
WORKDIR /build
COPY webui/frontend/package.json webui/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webui/frontend/ ./
RUN npm run build

FROM nginx:stable-alpine@sha256:985220252f3863977e468f611ef118ebd01421289dd86ee1ae99cb068c3bce2b
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 8080
