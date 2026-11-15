# Build context: the REPOSITORY ROOT (the web app imports ../../contracts/typescript).
FROM node:22-alpine AS build
WORKDIR /src
COPY apps/web/package.json apps/web/package-lock.json apps/web/
RUN cd apps/web && npm ci
COPY contracts/typescript contracts/typescript
COPY apps/web apps/web
RUN cd apps/web && npm run build

# Non-root nginx (listens on 8080 / 8443; compose maps them to 80 / 443).
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/conf.d/gridora.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx/snippets /etc/nginx/snippets
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
