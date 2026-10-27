# The installer tags the already installed AstrBot image locally before building.
# Dependencies survive container recreation. Original Compose files stay untouched.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY requirements-tested.txt /tmp/companion-requirements.txt
RUN python -m ensurepip --upgrade && python -m pip install --no-cache-dir -r /tmp/companion-requirements.txt
