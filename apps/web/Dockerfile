FROM nginx:1.28-alpine
COPY apps/web/*.html apps/web/styles.css /usr/share/nginx/html/
COPY apps/web/src /usr/share/nginx/html/src
COPY infrastructure/docker/web-start.sh /docker-entrypoint.d/40-local-research.sh
RUN chmod 755 /docker-entrypoint.d/40-local-research.sh \
    && printf 'export const API_ORIGIN = "";\n' > /usr/share/nginx/html/src/runtime-config.mjs \
    && rm -f /etc/nginx/conf.d/default.conf
