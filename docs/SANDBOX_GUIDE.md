# 🧪 Guia: Deploy no OpenShift Developer Sandbox

## 1. Criar conta
- Acesse: https://developers.redhat.com/developer-sandbox
- Clique em **"Start your sandbox for free"**
- Faça login ou crie uma conta Red Hat (gratuita, sem cartão)
- Confirme o número de celular (obrigatório para evitar contas fraudulentas)

---

## 2. Instalar o CLI `oc`

```bash
# Linux
curl -LO https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz
tar xvf openshift-client-linux.tar.gz && sudo mv oc /usr/local/bin/

# macOS
brew install openshift-cli

# Windows
winget install RedHat.OpenShiftCLI
```

---

## 3. Login via token

1. No console web, clique no seu **nome (canto superior direito)**
2. Clique em **"Copy login command"**
3. Clique em **"Display Token"**
4. Copie e execute:

```bash
oc login --token=sha256~SEU_TOKEN_AQUI \
         --server=https://api.sandbox-m2.XXXX.openshiftapps.com:6443

# Verificar namespace disponível
oc project
# Saída esperada: Using project "seu-usuario-dev" on server ...
```

---

## 4. Build e push da imagem

O Sandbox **não faz build** — você precisa de uma imagem já publicada.
Use o **GitHub Container Registry (grátis)**:

```bash
# No seu repositório GitHub, ative o GitHub Actions
# O pipeline ci-cd.yml já faz o push para ghcr.io automaticamente
# Após o push, a imagem estará em: ghcr.io/SEU_USUARIO/devops-api:latest

# Para tornar a imagem pública (necessário para o Sandbox puxar sem Secret):
# GitHub → seu repositório → Packages → devops-api → Package settings → Make public
```

### Alternativa: build local com Podman

```bash
cd app/
podman build -t ghcr.io/SEU_USUARIO/devops-api:latest .
podman login ghcr.io -u SEU_USUARIO -p SEU_GITHUB_TOKEN
podman push ghcr.io/SEU_USUARIO/devops-api:latest
```

---

## 5. Atualizar a imagem no manifest

```bash
# Edite openshift/sandbox-deploy.yaml e substitua:
#   image: ghcr.io/SUA_ORG/devops-api:latest
# pela sua imagem real, por exemplo:
#   image: ghcr.io/joaosilva/devops-api:latest
```

---

## 6. Aplicar os manifests

```bash
# Garantir que está no namespace certo
oc project SEU_USUARIO-dev

# Aplicar tudo de uma vez
oc apply -f openshift/sandbox-deploy.yaml

# Acompanhar os pods subindo
oc get pods -w

# Verificar status dos deployments
oc rollout status deployment/rabbitmq
oc rollout status deployment/devops-api
```

---

## 7. Acessar a aplicação

```bash
# Obter a URL pública gerada automaticamente pelo Sandbox
oc get route devops-api -o jsonpath='{.spec.host}'

# Exemplo de saída:
# devops-api-joaosilva-dev.apps.sandbox-m2.ll9k.p1.openshiftapps.com

# Testar os endpoints
APP_URL=$(oc get route devops-api -o jsonpath='https://{.spec.host}')

curl $APP_URL/health
curl $APP_URL/ready
curl $APP_URL/metrics

# Publicar um evento
curl -X POST $APP_URL/events \
  -H "Content-Type: application/json" \
  -d '{"event_type":"test","payload":{"msg":"hello sandbox"},"source":"cli"}'
```

---

## 8. Ver logs

```bash
# Logs da API
oc logs -f deployment/devops-api

# Logs do RabbitMQ
oc logs -f deployment/rabbitmq

# Descrever pod (útil para debug)
oc describe pod -l app=devops-api
```

---

## 9. Acessar o RabbitMQ Management UI

O Sandbox não expõe portas diretas — use port-forward:

```bash
oc port-forward deployment/rabbitmq 15672:15672

# Agora acesse no navegador: http://localhost:15672
# Login: admin / sandbox-pass-123
```

---

## ⚠️ Limitações do Sandbox que afetam o projeto

| Limitação | Impacto | Solução |
|-----------|---------|---------|
| Pods deletados após 12h | RabbitMQ perde filas | Use `emptyDir` (já configurado no sandbox-deploy.yaml) |
| 1 namespace apenas | Sem ambientes staging/prod | Use sufixos nos nomes: `devops-api-staging` |
| Sem DaemonSets | Dynatrace OneAgent não funciona | Use Dynatrace SaaS com injeção via env vars apenas |
| Sem `cluster-admin` | Não instala operadores | Use ServiceMonitor nativo se disponível |
| SCC restricted-v2 | runAsUser fixo é rejeitado | Já ajustado no sandbox-deploy.yaml |

---

## 10. SonarQube — use SonarCloud no lugar

No Sandbox não há recursos para rodar SonarQube local. Use o **SonarCloud** (grátis para repos públicos):

1. Acesse https://sonarcloud.io → login com GitHub
2. Crie um projeto apontando para o seu repositório
3. Gere um token e adicione nos Secrets do GitHub:
   - `SONAR_TOKEN` → token gerado
   - `SONAR_HOST_URL` → `https://sonarcloud.io`

O pipeline `ci-cd.yml` já está configurado para isso.
