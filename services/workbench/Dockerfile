ARG BROWSER_IMAGE=p1-companion-browser:0.20.0
FROM ${BROWSER_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim antiword catdoc unrtf && rm -rf /var/lib/apt/lists/*
COPY *.py /opt/workbench/
WORKDIR /opt/workbench
USER 1001:1001
CMD ["python", "server.py"]
