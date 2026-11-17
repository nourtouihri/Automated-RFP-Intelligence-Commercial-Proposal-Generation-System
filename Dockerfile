FROM python:3.11.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip==26.2.1 && \
    python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.14.0+cpu && \
    python -m pip install -r requirements.txt

# The deck validator measures text with the installed font files; the slim base
# image ships none, so build() would fail with FontNotFound. DejaVu is the
# fallback every local run and the feasibility calibration measured with.
RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

COPY detection ./detection
COPY research ./research
COPY rag ./rag
COPY ingestion ./ingestion
COPY proposal ./proposal
COPY insights_agent ./insights_agent
COPY shared ./shared
COPY ui-preview ./ui-preview


COPY ["Cvs dataset", "./Cvs dataset"]

RUN addgroup --system olivesoft && \
    adduser --system --ingroup olivesoft olivesoft && \
    mkdir -p /data /models && \
    chown -R olivesoft:olivesoft /app /data /models

USER olivesoft

EXPOSE 8000 8001 8002 8003 8004 8005 8006

CMD ["uvicorn", "rag.main:app", "--host", "0.0.0.0", "--port", "8001"]
