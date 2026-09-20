# Implantacao na VPS sem Docker

Este documento descreve como instalar e manter esta aplicacao rodando na VPS
da mesma forma que ela roda atualmente neste ambiente.

## Como a aplicacao funciona hoje

Nao existe um processo unico rodando continuamente. O `cron` inicia tres
execucoes independentes a cada 15 minutos e a busca de distancia percorrida
a cada 6 horas:

- Envio do monitoramento de viagens do `site_alpha`.
- Sincronizacao das viagens encerradas do `site_alpha`.
- Envio da distancia percorrida pela Sascar.
- Envio do movimento diario pela Sascar.

O script `run-scheduled.sh` usa o ambiente virtual `.venv`, cria um lock para
evitar duas execucoes iguais ao mesmo tempo e grava os logs em `logs/`.

Para reproduzir o comportamento atual, nao e necessario executar
`--poll-reports` nem `--serve-api`.

## Premissas

Os comandos abaixo assumem:

- VPS com Ubuntu ou Debian.
- Acesso SSH com um usuario normal que possa usar `sudo`.
- O repositorio clonado em `/opt/automation`.
- O mesmo arquivo `.env` que ja funciona neste ambiente.

Se o repositorio estiver em outro caminho, substitua `/opt/automation` nos
comandos e nas entradas do `crontab`.

## 1. Conferir a VPS

Execute:

```bash
cat /etc/os-release
python3 --version
pwd
```

O ambiente atual usa Python 3.12.3. Python 3.12 e recomendado para manter o
mesmo ambiente, mas a aplicacao pode funcionar com outra versao compativel.

## 2. Instalar os requisitos do sistema

Execute cada linha separadamente:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip cron
sudo systemctl enable --now cron
sudo timedatectl set-timezone America/Sao_Paulo
```

Confira o fuso horario:

```bash
timedatectl
```

O fuso correto e importante porque os horarios do portal e os horarios do
`cron` devem ser interpretados como horario de Brasilia.

## 3. Preparar o ambiente Python

Entre na pasta do projeto e execute cada linha separadamente:

```bash
cd /opt/automation
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium
mkdir -p logs
chmod +x run-scheduled.sh
```

O comando do Playwright instala o navegador Chromium e as bibliotecas
necessarias para o Playwright funcionar em modo headless na VPS.

## 4. Configurar o arquivo `.env`

O arquivo `.env` nao e versionado pelo Git. Portanto, ele nao vem quando o
repositorio e clonado.

A forma recomendada e copiar para a VPS o `.env` que ja funciona neste
ambiente. Execute o comando `scp` na maquina onde o arquivo esta, substituindo
usuario, IP e caminho:

```bash
scp /home/dionathan/code/automation/.env usuario@IP_DA_VPS:/opt/automation/.env
```

Depois, na VPS:

```bash
cd /opt/automation
chmod 600 .env
```

Se nao for possivel copiar o arquivo, crie-o manualmente:

```bash
cd /opt/automation
nano .env
```

Use esta estrutura e preencha os valores reais:

```env
APP_ENV=production
HEADLESS=true
SLOW_MO_MS=0
DEFAULT_TIMEOUT_MS=30000
TIMEZONE=America/Sao_Paulo

SITE_SOFTLOG_BASE_URL=https://app.softlogbrasil.com.br
SITE_SOFTLOG_USERNAME=USUARIO_SOFTLOG
SITE_SOFTLOG_PASSWORD=SENHA_SOFTLOG

SITE_SASCAR_BASE_URL=https://telemetria.sascar.com.br
SITE_SASCAR_USUARIO=USUARIO_SASCAR
SITE_SASCAR_LOGIN=LOGIN_SASCAR
SITE_SASCAR_PASSWORD=SENHA_SASCAR
SITE_SASCAR_FILIAL_VEICULO=MATRIZ
SASCAR_WINDOW_HOURS=24

RECEIVER_BASE_URL=https://app.axionsoft.com.br
RECEIVER_API_KEY=
RECEIVER_WEBHOOK_SECRET=SEGREDO_COMPARTILHADO
RECEIVER_VIAGEM_ATUAL_PATH=/api/integracoes/viagem-atual
RECEIVER_CLOSED_TRIPS_PATH=/api/integracoes/viagens
RECEIVER_MOVIMENTO_DIARIO_PATH=/api/integracoes/movimento-diario
RECEIVER_HISTORICO_QUILOMETRAGEM_PATH=/api/integracoes/historico-quilometragem
RECEIVER_TIMEOUT_SECONDS=30
RECEIVER_DEFAULT_BUSINESS_UNIT=CHAPECO
RECEIVER_DEFAULT_CUSTOMER=BRF S.A. CHAPECO/SC

CLOSED_TRIPS_CUTOFF_DATE=01/08/2026
CLOSED_TRIPS_BATCH_SIZE=100

# O cron ja controla os intervalos. Mantenha estes valores desativados.
MONITORING_TRIPS_POLL_ENABLED=false
DAILY_TRIP_SUMMARY_POLL_ENABLED=false
```

Inicialize o banco operacional depois de configurar o `.env`:

```bash
.venv/bin/python runner.py --init-automation-db
```

O valor de `RECEIVER_WEBHOOK_SECRET` deve ser exatamente igual ao segredo
configurado na aplicacao que recebe os dados.

`CLOSED_TRIPS_CUTOFF_DATE` e a data inicial da primeira sincronizacao de
viagens encerradas. Use a primeira data que realmente deve ser processada.

## 5. Preservar o estado anterior

O arquivo `automation_state.sqlite3` guarda o checkpoint e o historico de
envio das viagens encerradas. Sem esse arquivo, a primeira execucao da VPS
processara novamente desde `CLOSED_TRIPS_CUTOFF_DATE`.

Para manter o estado atual, copie tambem o arquivo para a VPS:

```bash
scp /home/dionathan/code/automation/automation_state.sqlite3 usuario@IP_DA_VPS:/opt/automation/automation_state.sqlite3
```

Copie esse arquivo quando nenhum job estiver escrevendo nele. Nao e necessario
copiar a pasta `logs/`.

## 6. Testar sem enviar dados

Na VPS, execute os testes abaixo separadamente:

```bash
cd /opt/automation
.venv/bin/python3 runner.py --test-login --site site_alpha
.venv/bin/python3 runner.py --push-monitoring-trips --dry-run
.venv/bin/python3 runner.py --sync-closed-trips --dry-run
.venv/bin/python3 runner.py --push-distancia-percorrida --dry-run
.venv/bin/python3 runner.py --push-movimento-diario --dry-run
```

Os comandos com `--dry-run` fazem a coleta e mostram os dados, mas nao enviam
os dados para a aplicacao receptora.

Se algum teste falhar, corrija o problema antes de configurar o `cron`.

## 7. Ativar a execucao automatica

Abra o `crontab` do mesmo usuario que e dono do projeto:

```bash
crontab -e
```

Adicione estas quatro linhas:

```cron
0,15,30,45 * * * * /opt/automation/run-scheduled.sh --push-monitoring-trips
2,17,32,47 * * * * /opt/automation/run-scheduled.sh --sync-closed-trips
4 0,6,12,18 * * * /opt/automation/run-scheduled.sh --push-distancia-percorrida
6,21,36,51 * * * * /opt/automation/run-scheduled.sh --push-movimento-diario
```

Cada linha do `crontab` e um comando independente. Nao coloque barras `\`
nessas linhas e nao junte as quatro linhas em um comando.

Confira se foram gravadas:

```bash
crontab -l
systemctl is-active cron
```

## 8. Conferir os logs

Os arquivos ficam em `/opt/automation/logs/`:

```bash
ls -lh /opt/automation/logs/
tail -f /opt/automation/logs/push-monitoring-trips.log
```

Os demais logs sao:

```text
push-monitoring-trips.log
sync-closed-trips.log
push-distancia-percorrida.log
push-movimento-diario.log
```

Cada job tambem possui um arquivo `.lock`. O lock nao impede a proxima
execucao depois que o processo termina; ele apenas impede sobreposicao do
mesmo job.

## Comandos separados e comandos em varias linhas

Quando um comando Shell termina uma linha com `\`, a linha seguinte continua
sendo o mesmo comando. Por exemplo:

```bash
comando principal \
  --opcao-1 valor \
  --opcao-2 valor
```

Isso e um unico comando dividido em tres linhas para facilitar a leitura.

Ja estas linhas sao tres comandos diferentes:

```bash
comando-1
comando-2
comando-3
```

Na instalacao desta aplicacao, as linhas de `apt`, `venv`, `pip` e Playwright
devem ser executadas uma por vez, na ordem apresentada. As quatro linhas do
`crontab` permanecem separadas.

## Atualizar a aplicacao

Quando houver uma nova versao no repositorio:

```bash
cd /opt/automation
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
```

Os jobs seguintes ja usarao o codigo atualizado, pois cada execucao do `cron`
inicia um novo processo Python.

## Observacoes importantes

- Os quatro jobs atuais nao dependem do MySQL; eles usam o SQLite para estado.
- A API HTTP nao esta sendo executada pelo procedimento atual.
- Os logs podem crescer bastante. Configure rotacao de logs se a VPS tiver
  pouco espaco em disco.
- Nao publique o `.env` no Git nem envie seus segredos em mensagens.

## Nova arquitetura assincrona

Para ativar a nova integracao, o MySQL usado pelo servico deve ser separado do
banco do Laravel. Redis tambem deve ficar local ou em rede privada.

Adicione ao `.env` pelo menos:

```env
MYSQL_DATABASE=automation
MYSQL_USER=automation
MYSQL_PASSWORD=UMA_SENHA_FORTE
REDIS_URL=redis://localhost:6379/0
AUTOMATION_CLIENT_ID=laravel-prod
AUTOMATION_CLIENT_SECRET=SEGREDO_HMAC
AUTOMATION_CALLBACK_URL=https://dominio-do-laravel/api/integrations/automation/v1/webhooks
AUTOMATION_WEBHOOK_CLIENT_ID=automation_prod
AUTOMATION_WEBHOOK_SECRET=SEGREDO_WEBHOOK
```

Instale Redis e a dependencia Python antes de ativar os processos:

```bash
sudo apt install -y redis-server
sudo systemctl enable --now redis-server
.venv/bin/python -m pip install -r requirements.txt
```

A API, o worker e o scheduler devem ser processos separados. Em uma VPS com
baixa concorrencia, um worker com uma thread e suficiente:

```bash
./run-automation-worker.sh
python3 runner.py --serve-api
python3 runner.py --automation-scheduler
```

Use `systemd` ou outro supervisor para reiniciar os tres processos. Nao rode o
scheduler assincrono dentro da API e nao habilite simultaneamente o cron legado
para a mesma coleta.
