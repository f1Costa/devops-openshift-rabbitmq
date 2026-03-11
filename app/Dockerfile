# ──────────────────────────────────────────────
# Stage 1 — build / dependencies
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ──────────────────────────────────────────────
# Stage 2 — runtime (imagem mínima)
# ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Usuário não-root (obrigatório para OpenShift SCC restricted)
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# OpenShift: qualquer UID deve ter permissão de escrita
RUN chown -R 1001:0 /app && chmod -R g=u /app

USER 1001

EXPOSE 8000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
