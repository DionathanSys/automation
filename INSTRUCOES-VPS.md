# Implantacao na VPS sem Docker

O servico roda como API e worker em uma unica VPS. A API recebe jobs sob
demanda e o worker executa Playwright. Nao configure cron, polling ou scheduler
para iniciar coletas.

## Premissas

- Ubuntu ou Debian com Python 3, MySQL e Redis acessiveis.
- Repositorio em `/opt/automation`.
- Credenciais reais armazenadas somente no `.env` da VPS.
- Acesso de rede aos portais Softlog e Sascar.

## Instalar pela primeira vez

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
sudo mkdir -p /opt/automation
sudo chown "$USER":"$USER" /opt/automation
cd /opt/automation
git clone URL_DO_REPOSITORIO .
cp .env.example .env
chmod 600 .env
```

Configure no `.env` o acesso ao MySQL, Redis, Softlog, Sascar e as credenciais
HMAC da integracao. Use `SITE_SOFTLOG_*` para o Softlog. Nao adicione variaveis
`RECEIVER_*`, `STATE_SQLITE_*` ou `*_POLL_*`.

Depois de preencher o `.env`, execute o atualizador versionado:

```bash
cd /opt/automation
./update-vps.sh
```

Ele cria o `venv`, instala dependencias, instala o Chromium, executa as
migrations, instala as unidades systemd e reinicia a API e o worker.

O script pressupoe que MySQL e Redis ja estejam acessiveis. A API e o worker
sao instalados como `automation-api.service` e `automation-worker.service`.
Nao use cron para criar jobs.

Verifique a API:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

## Acompanhar e depurar jobs

O `job_id` retornado pelo Filament pode ser acompanhado diretamente na VPS:

```bash
cd /opt/automation
.venv/bin/python runner.py --watch-job JOB_ID
.venv/bin/python runner.py --inspect-job JOB_ID
sudo journalctl -fu automation-api
sudo journalctl -fu automation-worker
```

Para uma tela no Filament, use `GET /api/v1/jobs` para a lista e
`GET /api/v1/jobs/{job_id}/diagnostics` para tentativas, erros, eventos e
entregas de webhook. Esses endpoints usam a mesma autenticacao HMAC.

## Atualizar a VPS

Antes de atualizar, confirme que o `.env` local nao sera alterado pelo Git:

```bash
cd /opt/automation
./update-vps.sh
```

O script bloqueia a atualizacao se houver alteracoes locais rastreadas. Para
usar outro usuario nos servicos:

```bash
AUTOMATION_SERVICE_USER=automation ./update-vps.sh
```

Confirme os logs e a prontidao:

```bash
sudo journalctl -u automation-api -u automation-worker -n 100 --no-pager
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```
