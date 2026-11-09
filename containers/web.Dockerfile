FROM caddy@sha256:c3d7ee5d2b11f9dc54f947f68a734c84e9c9666c92c88a7f30b9cba5da182adb
RUN setcap -r /usr/bin/caddy
ENV XDG_DATA_HOME=/tmp/caddy-data XDG_CONFIG_HOME=/tmp/caddy-config
COPY apps/web/dist /srv
COPY infra/caddy/local.Caddyfile /etc/caddy/local.Caddyfile
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["caddy"]
CMD ["run", "--config", "/etc/caddy/local.Caddyfile", "--adapter", "caddyfile"]
