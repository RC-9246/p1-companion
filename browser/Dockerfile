FROM soulter/astrbot:v4.29.1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends chromium ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python -m ensurepip --upgrade && python -m pip install --no-cache-dir playwright==1.64.0
RUN useradd --uid 1001 --create-home companion
WORKDIR /opt/browser
COPY *.py ./
USER 1001:1001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT []
CMD ["python", "broker.py"]
