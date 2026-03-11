# 🚀 DevOps Reference API

Projeto de referência para demonstração de stack DevOps completa, cobrindo os requisitos da vaga de **Analista DevOps**.

---

## 📐 Arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Actions                           │
│                                                                 │
│  push → [Quality] → [Build & Push] → [Deploy] → [Smoke Test]   │
│             │              │              │                     │
│          SonarQube      ghcr.io      OpenShift     Dynatrace   │
│          (SAST)         (image)      (cluster)     (event)     │
└─────────────────────────────────────────────────────────────────┘

┌───────────────────────── OpenShift Namespace ─────────────────┐
│                                                               │
│  Route (HTTPS) → Service → Deployment (devops-api x2)        │
│                                    │                          │
│                               RabbitMQ (StatefulSet)          │
│                                                               │
│  ServiceMonitor → Prometheus → Grafana                        │
│  PrometheusRule → AlertManager                                │
│  Dynatrace OneAgent (DaemonSet)                               │
└───────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Estrutura do Projeto

```
devops-project/
├── app/
│   ├── main.py              # FastAPI — endpoints, Prometheus, RabbitMQ
│   ├── requirements.txt
│   └── Dockerfile           # Multi-stage, usuário não-root (OpenShift SCC)
│
├── tests/
│   └── test_api.py          # Testes unitários + cobertura
│
├── .github/
│   └── workflows/
│       └── ci-cd.yml        # Pipeline completo (5 jobs)
│
├── openshift/
│   ├── 00-namespace.yaml
│   ├── deployment.yaml      # Deployment + liveness/readiness + Dynatrace
│   ├── service-route-hpa.yaml  # Service, Route, HPA, ServiceMonitor, PrometheusRule
│   └── rabbitmq.yaml        # StatefulSet + Service + Secret
│
├── ansible/
│   ├── inventory/hosts.ini
│   ├── playbooks/deploy.yml
│   └── roles/
│       ├── app-deploy/tasks/main.yml
│       ├── rabbitmq-setup/tasks/main.yml
│       └── monitoring-setup/tasks/main.yml
│
├── docs/
│   └── prometheus.yml       # Config Prometheus (dev local)
│
├── docker-compose.yml       # Stack local completa
└── sonar-project.properties # Configuração SonarQube
```

---

## ⚡ Início Rápido (Ambiente Local)

### Pré-requisitos
- Docker + Docker Compose
- Python 3.12+

### 1. Subir a stack local

```bash
docker compose up -d
```

Serviços disponíveis:
| Serviço     | URL                         |
|-------------|-----------------------------|
| API         | http://localhost:8000       |
| Swagger UI  | http://localhost:8000/docs  |
| RabbitMQ    | http://localhost:15672      |
| Prometheus  | http://localhost:9090       |
| Grafana     | http://localhost:3000       |
| SonarQube   | http://localhost:9000       |

### 2. Rodar os testes

```bash
pip install -r app/requirements.txt pytest pytest-cov pytest-asyncio
pytest tests/ --cov=app --cov-report=term-missing -v
```

### 3. Análise SonarQube local

```bash
# Aguardar SonarQube iniciar (~2 min) e criar projeto em http://localhost:9000
sonar-scanner \
  -Dsonar.host.url=http://localhost:9000 \
  -Dsonar.token=SEU_TOKEN_LOCAL
```

---

## 🔄 Pipeline CI/CD (GitHub Actions)

### Fluxo completo

```
git push → develop   →  quality → build → deploy-staging  → smoke-test
git push → main      →  quality → build → deploy-production → smoke-test
```

### Jobs

| Job | O que faz |
|-----|-----------|
| `quality` | Pytest + cobertura + SonarQube Quality Gate |
| `build` | Build multi-stage + push para ghcr.io + evento Dynatrace |
| `deploy-staging` | `oc apply` no namespace `-staging` + evento Dynatrace |
| `deploy-production` | `oc apply` no namespace produção + janela de observação Dynatrace |
| `smoke-test` | Health check + readiness check pós-deploy |

### Secrets necessários no GitHub

```
SONAR_TOKEN              # Token do SonarQube
SONAR_HOST_URL           # URL da instância SonarQube
OPENSHIFT_SERVER_URL     # https://api.seu-cluster:6443
OPENSHIFT_TOKEN          # Token do Service Account
OPENSHIFT_CLUSTER_DOMAIN # apps.seu-cluster.example.com
DYNATRACE_ENV_URL        # https://xxx.live.dynatrace.com
DYNATRACE_API_TOKEN      # Token com escopo v2.events.ingest
```

---

## ☸️ OpenShift / Kubernetes

### Aplicar manualmente

```bash
# Login
oc login --token=<token> --server=https://api.cluster:6443

# Aplicar tudo
oc apply -f openshift/ --namespace devops-project

# Verificar rollout
oc rollout status deployment/devops-api -n devops-project

# Ver logs
oc logs -f deployment/devops-api -n devops-project
```

### Probes configuradas

| Probe | Endpoint | Função |
|-------|----------|--------|
| Liveness | `/health` | Reinicia o pod se a API travar |
| Readiness | `/ready` | Remove do balanceador se RabbitMQ cair |

### HPA (Auto Scaling)

| Condição | Ação |
|----------|------|
| CPU > 70% | Escala até 8 réplicas |
| CPU < 70% | Reduz para mínimo 2 |

---

## 🤖 Ansible

### Deploy completo

```bash
# Todas as roles
ansible-playbook playbooks/deploy.yml \
  -i inventory/hosts.ini \
  -e "image_tag=sha-abc1234 app_env=production" \
  --ask-vault-pass

# Apenas a aplicação (sem setup de infra)
ansible-playbook playbooks/deploy.yml \
  -i inventory/hosts.ini \
  -e "setup_rabbitmq=false setup_monitoring=false" \
  --tags app-deploy
```

### Roles disponíveis

| Role | Responsabilidade |
|------|-----------------|
| `app-deploy` | Aplica manifests, substitui tag da imagem, configura Dynatrace env vars |
| `rabbitmq-setup` | Deploya StatefulSet, aguarda ready, cria filas com DLQ |
| `monitoring-setup` | Aplica ServiceMonitor, cria Secret Dynatrace, anota Deployment |

---

## 📊 Observabilidade — Dynatrace

### Integração CI/CD

O pipeline envia **eventos de deployment** ao Dynatrace em dois momentos:

1. **Build** → `CUSTOM_DEPLOYMENT` com metadados do commit e tag da imagem
2. **Deploy** → `CUSTOM_DEPLOYMENT` com janela de 15 minutos para correlação automática de anomalias

### Variáveis injetadas no pod

```yaml
DT_RELEASE_VERSION: <image-tag>
DT_RELEASE_STAGE:   production | staging
DT_RELEASE_PRODUCT: devops-api
```

Isso permite ao Dynatrace correlacionar métricas, erros e traces com a versão exata deployada.

### Métricas Prometheus expostas

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `http_requests_total` | Counter | Total de requisições por método, rota e status |
| `http_request_duration_seconds` | Histogram | Latência das requisições (P50, P95, P99) |
| `rabbitmq_messages_sent_total` | Counter | Mensagens publicadas por fila |
| `rabbitmq_connection_status` | Gauge | 1=conectado, 0=desconectado |

### SLOs recomendados

```
Disponibilidade: http_requests_total{status!~"5.."} / http_requests_total > 99.5%
Latência P95:    histogram_quantile(0.95, http_request_duration_seconds) < 0.5s
```

---

## 🐇 RabbitMQ — Filas

| Fila | Produtor | Consumidor esperado |
|------|----------|---------------------|
| `orders` | `POST /orders` | Serviço de processamento de pedidos |
| `events` | `POST /events` | Serviço de auditoria/notificações |

Todas as filas são `durable: true` com TTL de 24h e Dead Letter Exchange configurado.

---

## 🔍 SonarQube — Quality Gate

Configurado em `sonar-project.properties`. O pipeline **bloqueia o build** se:
- Cobertura de código < 80%
- Bugs críticos detectados
- Code smells de alta severidade

---

## 🔐 Segurança

- Imagem Docker roda com **usuário não-root (UID 1001)** — compatível com OpenShift SCC `restricted`
- `readOnlyRootFilesystem: true` — sistema de arquivos somente-leitura
- `capabilities: drop: ["ALL"]` — sem capabilities Linux
- Secrets via `oc secret` / Vault (nunca em plaintext no repositório)
- HTTPS obrigatório via Route com `insecureEdgeTerminationPolicy: Redirect`

---

## 📝 Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `APP_ENV` | `development` | Ambiente de execução |
| `APP_VERSION` | `1.0.0` | Versão da aplicação |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | URL de conexão AMQP |
