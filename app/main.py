import os
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import aio_pika
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from pydantic import BaseModel

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("devops-api")

# ──────────────────────────────────────────────
# Prometheus Metrics
# ──────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)
RABBITMQ_MESSAGES_SENT = Counter(
    "rabbitmq_messages_sent_total",
    "Total messages published to RabbitMQ",
    ["queue"],
)
RABBITMQ_CONNECTION_STATUS = Gauge(
    "rabbitmq_connection_status",
    "RabbitMQ connection status (1=connected, 0=disconnected)",
)

# ──────────────────────────────────────────────
# Config from environment
# ──────────────────────────────────────────────
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
APP_ENV      = os.getenv("APP_ENV", "development")
APP_VERSION  = os.getenv("APP_VERSION", "1.0.0")

# ──────────────────────────────────────────────
# RabbitMQ connection holder
# ──────────────────────────────────────────────
rabbitmq_connection: Optional[aio_pika.abc.AbstractRobustConnection] = None


async def get_rabbitmq_channel():
    global rabbitmq_connection
    if rabbitmq_connection is None or rabbitmq_connection.is_closed:
        rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
        RABBITMQ_CONNECTION_STATUS.set(1)
        logger.info("RabbitMQ connection established")
    return await rabbitmq_connection.channel()


# ──────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DevOps API — env=%s version=%s", APP_ENV, APP_VERSION)
    try:
        await get_rabbitmq_channel()
    except Exception as exc:
        logger.warning("Could not connect to RabbitMQ on startup: %s", exc)
        RABBITMQ_CONNECTION_STATUS.set(0)
    yield
    if rabbitmq_connection and not rabbitmq_connection.is_closed:
        await rabbitmq_connection.close()
        logger.info("RabbitMQ connection closed")


# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────
app = FastAPI(
    title="DevOps Reference API",
    description="API de referência para demonstração de stack DevOps",
    version=APP_VERSION,
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# Middleware — metrics + Dynatrace trace header
# ──────────────────────────────────────────────
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)

    # Dynatrace — propagate trace context
    if "x-dynatrace" in request.headers:
        response.headers["x-dynatrace"] = request.headers["x-dynatrace"]

    return response


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
class EventPayload(BaseModel):
    event_type: str
    payload: dict
    source: str = "api"


class OrderPayload(BaseModel):
    order_id: str
    customer_id: str
    items: list[dict]
    total: float


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.get("/health", tags=["Observability"])
async def health_check():
    """Liveness probe — usado pelo OpenShift."""
    return {"status": "healthy", "version": APP_VERSION, "env": APP_ENV}


@app.get("/ready", tags=["Observability"])
async def readiness_check():
    """Readiness probe — verifica dependências críticas."""
    checks = {"rabbitmq": False}
    try:
        await get_rabbitmq_channel()
        checks["rabbitmq"] = True
    except Exception:
        pass

    all_ready = all(checks.values())
    status_code = 200 if all_ready else 503
    return JSONResponse(
        content={"status": "ready" if all_ready else "not_ready", "checks": checks},
        status_code=status_code,
    )


@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Endpoint Prometheus — coletado pelo ServiceMonitor do OpenShift."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/events", tags=["Events"], status_code=202)
async def publish_event(event: EventPayload):
    """Publica um evento genérico no RabbitMQ."""
    try:
        channel = await get_rabbitmq_channel()
        queue = await channel.declare_queue("events", durable=True)
        message = aio_pika.Message(
            body=json.dumps(event.model_dump()).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await channel.default_exchange.publish(message, routing_key=queue.name)
        RABBITMQ_MESSAGES_SENT.labels(queue="events").inc()
        logger.info("Event published: type=%s source=%s", event.event_type, event.source)
        return {"status": "accepted", "queue": "events"}
    except Exception as exc:
        logger.error("Failed to publish event: %s", exc)
        raise HTTPException(status_code=500, detail="Message broker unavailable")


@app.post("/orders", tags=["Orders"], status_code=202)
async def create_order(order: OrderPayload):
    """Cria um pedido e publica na fila de processamento."""
    try:
        channel = await get_rabbitmq_channel()
        queue = await channel.declare_queue("orders", durable=True)
        message = aio_pika.Message(
            body=json.dumps(order.model_dump()).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await channel.default_exchange.publish(message, routing_key=queue.name)
        RABBITMQ_MESSAGES_SENT.labels(queue="orders").inc()
        logger.info("Order queued: id=%s customer=%s", order.order_id, order.customer_id)
        return {"status": "accepted", "order_id": order.order_id}
    except Exception as exc:
        logger.error("Failed to queue order: %s", exc)
        raise HTTPException(status_code=500, detail="Message broker unavailable")


@app.get("/orders/{order_id}", tags=["Orders"])
async def get_order(order_id: str):
    """Exemplo de endpoint — em produção consultaria um banco de dados."""
    return {"order_id": order_id, "status": "processing", "message": "Consulte o banco de dados para status real"}
