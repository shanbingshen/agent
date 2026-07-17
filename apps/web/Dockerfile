FROM node:24.18.0-alpine AS build
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml* ./
RUN npm install
COPY apps/web ./
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.29.0-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
