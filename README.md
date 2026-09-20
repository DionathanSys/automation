# Automacao multi-site com Playwright

Base inicial para coletar relatorios HTML em multiplos sites, percorrer paginacao e salvar dados no MySQL com upsert.

Fluxo atual recomendado para producao no `site_alpha`:

- `monitoring_trips`: coleta e envia o payload direto para a aplicacao principal
- `closed_trips`: consulta cada data com um dia anterior de sobreposicao, coleta viagens pela data de encerramento, armazena cada uma em SQLite e envia em lotes de 100

## O que ja existe

- Estrutura base para sites e relatorios
- Runner manual por linha de comando
- Scheduler opcional
- Persistencia MySQL com criacao automatica de tabelas
- Historico de execucao em `job_runs`
- Base generica para extracao de tabelas HTML paginadas
- Dois sites placeholder e quatro relatorios placeholder

## Instalar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
cp .env.example .env
```

## Estado local em SQLite

O coletor salva em `SQLite` o checkpoint e o historico de cada viagem encerrada. O historico inclui o ultimo payload coletado, a data em que a Softlog a informou, quantidade de tentativas, erro da ultima tentativa, lote e o status de recebimento pela API (`pending`, `failed` ou `accepted`). Uma viagem aceita so e reenviada se os dados coletados forem alterados.

`accepted` confirma que a API respondeu com sucesso ao recebimento do lote. Como o processamento do receptor e assincrono, esse status nao confirma a criacao final da viagem no sistema receptor.

Arquivo local de estado:

```bash
automation_state.sqlite3
```

Configuracoes novas no `.env`:

```env
STATE_SQLITE_PATH=automation_state.sqlite3
RECEIVER_BASE_URL=https://app.axionsoft.com.br
RECEIVER_API_KEY=
RECEIVER_MONITORING_TRIPS_PATH=/api/monitoring-trips
RECEIVER_CLOSED_TRIPS_PATH=/api/integracoes/viagens
RECEIVER_WEBHOOK_SECRET=
RECEIVER_TIMEOUT_SECONDS=30
RECEIVER_DEFAULT_BUSINESS_UNIT=CHAPECO
RECEIVER_DEFAULT_CUSTOMER=BRF S.A. CHAPECO/SC
CLOSED_TRIPS_CUTOFF_DATE=01/08/2026
CLOSED_TRIPS_BATCH_SIZE=100
```

## Executar manualmente

```bash
python3 runner.py --list
python3 runner.py --site site_alpha --report financial_summary
python3 runner.py --site site_beta --report sales_by_day --filters '{"start_date":"2026-01-01","end_date":"2026-01-31"}'
python3 runner.py --run-all
python3 runner.py --test-monitoring-trips --site site_alpha
python3 runner.py --test-daily-trip-summary --site site_alpha
python3 runner.py --push-monitoring-trips
python3 runner.py --sync-closed-trips
python3 runner.py --closed-trips-status
python3 runner.py --closed-trips-status --competence-date 2026-08-13
python3 runner.py --audit-closed-trips --start-date 01/08/2026 --end-date 13/08/2026
```

`--audit-closed-trips` consulta novamente a Softlog e lista os numeros de viagem que aparecem nela, mas ainda nao existem no historico local. O comando encerra com codigo `2` quando encontra divergencias, permitindo uso em monitoramento agendado.

## Executar scheduler

```bash
python3 runner.py --scheduler
```

## API e polling do dashboard

Para o fluxo novo de integracao com a aplicacao principal, prefira:

```bash
python3 runner.py --poll-reports
```

Esse polling:

- envia `monitoring_trips` sem persistencia local
- sincroniza `closed_trips` por data e lote
- salva em `SQLite` o checkpoint da data enviada com sucesso

Relatorio pronto para persistir no MySQL e expor via API:

- `site_alpha / monitoring_trips`
- `site_alpha / daily_trip_summary`
- Campos salvos: `plate`, `started_at`, `current_location`, `status`, `weight`, `destination`, `collected_at`
- Campos salvos no resumo diario: `report_date`, `plate`, `fleet`, `vehicle_id`, `completed_trip_count`, `total_suggested_km`, `total_driven_km`, `collected_at`

Comandos:

```bash
python3 runner.py --poll-reports
python3 runner.py --serve-api
```

Scripts auxiliares:

```bash
./run-monitoring-trips-poller.sh
./run-daily-trip-summary-site-alpha.sh
./run-poller.sh
./run-api.sh
```

Endpoint HTTP:

```text
GET /api/site-alpha/monitoring-trips
GET /api/site-alpha/daily-trip-summaries
GET /health
```

Se `API_KEY` estiver preenchida no `.env`, envie o header `X-API-Key`.

## Nova API de automacao

A integracao assincrona usa MySQL como banco operacional, Redis como fila e um
worker Dramatiq para executar Playwright fora do processo HTTP. O servico API
nao deve executar browsers durante uma requisicao.

Inicialize os processos separadamente:

```bash
python3 runner.py --init-automation-db
python3 runner.py --serve-api
./run-automation-worker.sh
python3 runner.py --automation-scheduler
```

Endpoints da versao 1:

```text
GET  /health
GET  /ready
POST /api/v1/jobs
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/result
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
GET  /api/v1/collectors
GET  /api/v1/system/status
POST /api/v1/system/pause
POST /api/v1/system/resume
```

As chamadas `/api/v1` exigem HMAC v1 com `X-Client-ID`, `X-Timestamp`,
`X-Nonce`, `X-Signature` e `X-Signature-Version: v1`. O cliente configurado por
`AUTOMATION_CLIENT_ID` e `AUTOMATION_CLIENT_SECRET` e criado automaticamente
no banco operacional durante o startup da API.

Os fluxos legados de envio direto para o receptor continuam disponiveis durante
a migracao. Nao habilite os dois fluxos para a mesma coleta em producao ate que
a importacao Laravel esteja validada.

Variaveis novas no `.env`:

```env
MONITORING_TRIPS_POLL_ENABLED=false
MONITORING_TRIPS_POLL_INTERVAL_SECONDS=300
DAILY_TRIP_SUMMARY_POLL_ENABLED=false
DAILY_TRIP_SUMMARY_POLL_INTERVAL_SECONDS=300
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=
```

Uso em producao:

1. Suba a API com `python3 runner.py --serve-api`
2. Rode o polling no mesmo processo via `*_POLL_ENABLED=true` ou em processo separado com `python3 runner.py --poll-reports`
3. Em cenarios com mais de uma replica da API, prefira um processo separado de polling para evitar coletas duplicadas

## Estrutura prevista por site e relatorio

- `automation/sites/site_alpha.py`: login e navegacao do primeiro site
- `automation/sites/site_beta.py`: login e navegacao do segundo site
- `automation/reports/site_alpha_reports.py`: schemas das tabelas do primeiro site
- `automation/reports/site_beta_reports.py`: schemas das tabelas do segundo site

Cada relatorio define sua propria tabela MySQL e sua propria chave unica para `upsert`.

## Proximos passos

1. Preencher as credenciais no `.env`
2. Substituir URLs, seletores e login em `automation/sites/site_alpha.py` e `automation/sites/site_beta.py`
3. Ajustar colunas e chaves unicas em `automation/reports/`
4. Configurar os jobs reais em `automation/jobs/registry.py`
5. Habilitar agendamentos por cron quando os fluxos estiverem validados
