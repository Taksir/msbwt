# This is the Docker-Hub linux/amd64 manifest digest resolved on 2026-08-08.
# It has not been built or run on this host, so it is a resolved reference, not
# a verified oracle image.  Callers may override it with another recorded
# immutable image reference when testing a different CPU architecture.
ARG PYTHON27_BASE=python@sha256:c934af72b8bd03b9804d5bde2569c320926e70392d708d113a2e71bcf98c8a20
FROM --platform=linux/amd64 ${PYTHON27_BASE}
ARG PYTHON27_BASE

LABEL org.opencontainers.image.title="MSBWT original 0.3.0 probe environment" \
      org.opencontainers.image.description="Python 2.7 oracle scaffold; resolved base reference not locally executed" \
      org.opencontainers.image.source-commit="7503346ec072ddb89520db86fef85569a9ba093a" \
      org.opencontainers.image.base-digest-status="resolved-but-not-locally-executed"

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ORACLE_BASE_IMAGE_REFERENCE=${PYTHON27_BASE} \
    ORACLE_BASE_IMAGE_STATUS=resolved-but-not-locally-executed

# Do not contact end-of-life Buster package endpoints before the probe starts.
# The full Python image normally inherits buildpack-deps; if a candidate lacks
# a compiler or library, let its captured pip/build command demonstrate that.

COPY reference/original-0.3.0/environment/ /oracle-harness/
RUN chmod 755 /oracle-harness/run-probe.sh

VOLUME ["/results"]
ENTRYPOINT ["/oracle-harness/run-probe.sh"]
