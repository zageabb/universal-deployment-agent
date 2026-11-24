# Disposable CI-only Ubuntu systemd test host; NEVER run on production Docker.
ARG UBUNTU_VERSION=24.04
FROM ubuntu:${UBUNTU_VERSION}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    systemd systemd-sysv python3 python3-venv ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
# Ubuntu 22.04's distribution jsonschema lacks Draft202012Validator.
# Install the same modern validation API in a TEST-ONLY venv while the
# disposable image is built; the running container has no network.
RUN python3 -m venv /opt/uda-v2-test-venv && \
    /opt/uda-v2-test-venv/bin/python -m pip install --no-cache-dir \
    'PyYAML>=6,<7' 'jsonschema>=4.20,<5' 'Flask>=3,<4'
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
