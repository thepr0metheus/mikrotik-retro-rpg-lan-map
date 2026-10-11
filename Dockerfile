FROM python:3.14-alpine
# Alpine's fixes come out sooner than a new base image: each build takes them.
RUN apk upgrade --no-cache

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
# The commit this image is: git archive writes it into VERSION, and /healthz names it.
# No commit in it means the code did not come by git archive — the build stops.
COPY VERSION ./VERSION
RUN if grep -q 'Format' VERSION; then echo "VERSION holds no commit: copy the code with git archive" >&2; exit 1; fi
COPY lan_map ./lan_map
COPY web ./web
COPY config ./config

# An ordinary user by default. A compose file may run the map as the owner of data/, so the
# snapshot and the layout there stay editable by that owner.
USER 1000:1000
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import os, sys, urllib.request; url = 'http://127.0.0.1:%s/healthz' % os.environ.get('LAN_MAP_PORT', '8080'); sys.exit(urllib.request.urlopen(url, timeout=2).status != 200)"

CMD ["python", "-m", "lan_map"]
