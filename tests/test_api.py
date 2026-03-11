import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

# Patch RabbitMQ before importing app
with patch("aio_pika.connect_robust", new_callable=AsyncMock):
    from app.main import app

client = TestClient(app)


class TestHealth:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_contains_version(self):
        response = client.get("/health")
        data = response.json()
        assert "version" in data
        assert "status" in data
        assert data["status"] == "healthy"

    def test_metrics_endpoint(self):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text


class TestOrders:
    @patch("app.main.get_rabbitmq_channel")
    def test_create_order_accepted(self, mock_channel):
        mock_ch = AsyncMock()
        mock_channel.return_value = mock_ch

        payload = {
            "order_id": "ORD-001",
            "customer_id": "CUST-42",
            "items": [{"sku": "ABC", "qty": 2}],
            "total": 99.90,
        }
        response = client.post("/orders", json=payload)
        assert response.status_code == 202
        assert response.json()["order_id"] == "ORD-001"

    @patch("app.main.get_rabbitmq_channel", side_effect=Exception("broker down"))
    def test_create_order_broker_failure(self, _):
        payload = {
            "order_id": "ORD-002",
            "customer_id": "CUST-43",
            "items": [],
            "total": 0,
        }
        response = client.post("/orders", json=payload)
        assert response.status_code == 500

    def test_get_order(self):
        response = client.get("/orders/ORD-999")
        assert response.status_code == 200
        assert response.json()["order_id"] == "ORD-999"


class TestEvents:
    @patch("app.main.get_rabbitmq_channel")
    def test_publish_event(self, mock_channel):
        mock_ch = AsyncMock()
        mock_channel.return_value = mock_ch

        payload = {
            "event_type": "user.created",
            "payload": {"user_id": "u1"},
            "source": "auth-service",
        }
        response = client.post("/events", json=payload)
        assert response.status_code == 202
        assert response.json()["queue"] == "events"
