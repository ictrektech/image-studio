ARG NODE_BASE_IMAGE=swr.cn-southwest-2.myhuaweicloud.com/ictrek/node:amd_22-alpine
ARG NGINX_BASE_IMAGE=swr.cn-southwest-2.myhuaweicloud.com/ictrek/nginx:amd_alpine

FROM ${NODE_BASE_IMAGE} AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM ${NGINX_BASE_IMAGE}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
RUN sed -i 's#</head>#  <script src="/runtime-config.js"></script>\\n</head>#' /usr/share/nginx/html/index.html
EXPOSE 80
ENTRYPOINT ["/docker-entrypoint.sh"]

