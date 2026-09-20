# Implantacao na VPS

O servico roda como API e worker em uma unica VPS. A API recebe jobs sob
demanda e o worker executa Playwright. Nao configure cron, polling ou
scheduler para iniciar coletas.

## Premissas

- Ubuntu ou Debian com Docker Engine e Compose plugin.
- Repositorio em `/opt/automation`.
- Credenciais reais armazenadas somente no `.env` da VPS.
- Acesso de rede aos portais Softlog e Sascar.

## Configuracao

```bash
sudo mkdir -p /opt/automation
sudo chown "$USER":"$USER" /opt/automation
cd /opt/automation
git clone URL_DO_REPOSITORIO .
cp .env.example .env
chmod 600 .env
```

Preencha no `.env`:

```env
MYSQL_PASSWORD=...
MYSQL_ROOT_PASSWORD=...
AUTOMATION_CLIENT_ID=laravel-prod
AUTOMATION_CLIENT_SECRET=...
AUTOMATION_CALLBACK_URL=https://erp.example.com/api/integrations/automation/v1/webhooks
AUTOMATION_WEBHOOK_CLIENT_ID=automation_prod
AUTOMATION_WEBHOOK_SECRET=...
SITE_SOFTLOG_USERNAME=...
SITE_SOFTLOG_PASSWORD=...
SITE_SASCAR_USUARIO=...
SITE_SASCAR_LOGIN=...
SITE_SASCAR_PASSWORD=...
```

Use `SITE_SOFTLOG_*` para as credenciais do Softlog. Nao adicione variaveis
`RECEIVER_*`, `STATE_SQLITE_*` ou `*_POLL_*`: esses fluxos foram removidos.

## Subir os servicos

```bash
docker compose up -d --build mysql redis
docker compose run --rm api python3 runner.py --init-automation-db
docker compose up -d api worker
docker compose ps
```

Verifique a API:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
docker compose logs -f api worker
```

A porta `8000` deve ficar protegida por firewall ou reverse proxy. Os endpoints
`/api/v1` exigem HMAC v1 e nao devem ser expostos sem autenticacao.

## Operacao

Listar collectors:

```bash
docker compose exec api python3 runner.py --list
```

Criar jobs pelo cliente Laravel usando `POST /api/v1/jobs`. O corpo minimo e:

```json
{
  "collector": "site_alpha_closed_trips",
  "parameters": {"from": "2026-09-01", "to": "2026-09-01"},
  "requested_by": "laravel"
}
```

Consulte o status e os resultados pelos endpoints do proprio job. O webhook de
conclusao usa `AUTOMATION_CALLBACK_URL` e assinatura configurada em
`AUTOMATION_WEBHOOK_SECRET`.

## Atualizacao

```bash
cd /opt/automation
git pull --ff-only
docker compose build
docker compose run --rm api python3 runner.py --init-automation-db
docker compose up -d api worker
```

Antes de atualizar, confira `docker compose logs api worker` e mantenha backup
do volume MySQL. O volume Redis e usado apenas para a fila e pode ser
reconstruido conforme a politica operacional da VPS.
