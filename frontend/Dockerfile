# Build context is the REPO ROOT (kept consistent with the backend image).
FROM node:22-alpine AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, so it has to be
# a build arg — setting it at runtime does nothing. And it must be an address the
# USER'S BROWSER can reach, not a container hostname: the fetch happens on the
# host, so "http://backend:8001" would fail to resolve.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8001
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
EXPOSE 3000
CMD ["npm", "run", "start"]
