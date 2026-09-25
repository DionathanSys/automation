# Automacao multi-site com Playwright

Servico de coleta sob demanda. A API cria jobs, o Redis enfileira e um worker
Dramatiq executa o Playwright. Nao existe scheduler, polling interno, envio
direto para receptor externo ou estado operacional em SQLite.

## Componentes

- FastAPI: recebe comandos e consulta jobs.
- MySQL: guarda jobs, resultados, eventos e estado operacional.
- Redis: fila Dramatiq.
- Worker: executa os collectors com baixa concorrencia.
- Alembic: controla o schema operacional.

## Instalar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
cp .env.example .env
```

Preencha no `.env` as credenciais MySQL, Redis, Softlog e Sascar. As variaveis
do primeiro site usam o prefixo `SITE_SOFTLOG_*`.

## Executar

Inicialize o banco operacional uma vez:

```bash
python3 runner.py --init-automation-db
```

Em processos separados, inicie a API e um worker:

```bash
python3 runner.py --serve-api
dramatiq automation.jobs.worker --processes 1 --threads 1
```

Com Docker Compose:

```bash
docker compose up --build
```

Em uma VPS sem Docker, use o atualizador versionado depois de configurar o
`.env`:

```bash
./update-vps.sh
```

Nao execute scheduler ou cron para criar jobs. Toda coleta deve ser disparada
por `POST /api/v1/jobs`.

## Collectors

Lista disponivel em `GET /api/v1/collectors` ou:

```bash
python3 runner.py --list
```

Collectors registrados:

- `site_alpha_monitoring_trips`
- `site_alpha_daily_trip_summary`
- `daily_trip_summary`
- `site_alpha_closed_trips`
- `sascar_daily_movement`
- `sascar_traveled_distance`

Para viagens encerradas, informe `parameters.from` e `parameters.to` em
`YYYY-MM-DD` ou `DD/MM/YYYY`.

A consulta da Softlog cobre todo o periodo solicitado e comeca dois dias antes
da data inicial. Depois, o collector mantem somente registros cujo `ended_at`
esteja dentro do periodo solicitado. Essa sobreposicao captura viagens longas
que comecaram antes, mas terminaram no periodo.

O collector `daily_trip_summary` recebe `parameters.from` e `parameters.to`,
com limites inclusivos, e retorna uma viagem por registro com
`numero_viagem`, `placa`, `cliente`, `destino`, `km_rodado`, `km_pago`,
`data_competencia`, `data_inicio`, `data_fim`, `possui_pendencia`,
`pendencias` e `motoristas`. O formato recomendado e `YYYY-MM-DD`; o formato
`DD/MM/YYYY` tambem e aceito. O campo legado `date` continua aceito para uma
execucao de um unico dia.

## API

Endpoints principais:

```text
GET  /health
GET  /ready
POST /api/v1/jobs
GET  /api/v1/jobs
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/diagnostics
GET  /api/v1/jobs/{job_id}/result
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
GET  /api/v1/collectors
GET  /api/v1/system/status
POST /api/v1/system/pause
POST /api/v1/system/resume
```

As chamadas `/api/v1` usam HMAC v1 com `X-Client-ID`, `X-Timestamp`, `X-Nonce`,
`X-Signature` e `X-Signature-Version: v1`.

Exemplo de criacao de job:

```json
{
  "collector": "site_alpha_closed_trips",
  "parameters": {
    "from": "2026-09-01",
    "to": "2026-09-01"
  },
  "requested_by": "laravel",
  "metadata": {}
}
```

## Migrations

```bash
alembic upgrade head
alembic current
alembic check
```

O cliente configurado por `AUTOMATION_CLIENT_ID` e
`AUTOMATION_CLIENT_SECRET` e criado automaticamente durante a inicializacao
do banco operacional.

## Diagnostico operacional

O Filament pode listar jobs com `GET /api/v1/jobs` e consultar o detalhe
completo de uma execucao em `GET /api/v1/jobs/{job_id}/diagnostics`. O detalhe
inclui parametros recebidos, tentativas do worker, erros, eventos e tentativas
de webhook.

Na VPS, os mesmos dados podem ser consultados diretamente:

```bash
.venv/bin/python runner.py --list-jobs --limit 20
.venv/bin/python runner.py --watch-job JOB_ID
.venv/bin/python runner.py --inspect-job JOB_ID
sudo journalctl -fu automation-api
sudo journalctl -fu automation-worker
```

## Estrutura

- `automation/sites/`: login, navegacao e extracao Playwright.
- `automation/collectors/`: collectors especificos de negocio.
- `automation/jobs/`: registry, worker e servico de jobs.
- `automation/db/`: conexao, schema operacional e migrations.
- `automation/services/webhook_service.py`: entrega de eventos ao callback
  configurado, sem enviar dados de coleta diretamente para sistemas legados.
