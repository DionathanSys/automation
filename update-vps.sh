#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POST_PULL=false
if [[ "${1:-}" == "--post-pull" ]]; then
    POST_PULL=true
fi

log() {
    printf '[update-vps] %s\n' "$*"
}

fail() {
    printf '[update-vps] ERRO: %s\n' "$*" >&2
    exit 1
}

as_root() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

cd "$ROOT"

[[ -d .git ]] || fail "O diretorio nao e um repositorio Git: $ROOT"
[[ -f .env ]] || fail "Arquivo .env nao encontrado em $ROOT"

if [[ "$POST_PULL" == false ]]; then
    if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
        fail "Existem alteracoes locais. Revise com git status antes de atualizar."
    fi

    log "Atualizando o codigo pelo Git."
    git pull --ff-only

    # Reexecuta a versao que acabou de chegar pelo Git.
    exec "$ROOT/update-vps.sh" --post-pull
fi

PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    log "Criando o ambiente virtual Python."
    python3 -m venv "$ROOT/.venv"
fi

log "Atualizando dependencias Python."
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$ROOT/requirements.txt"

log "Atualizando dependencias do Chromium."
as_root "$PYTHON" -m playwright install-deps chromium
"$PYTHON" -m playwright install chromium

log "Aplicando migrations do banco operacional."
"$PYTHON" "$ROOT/runner.py" --init-automation-db

SERVICE_USER="${AUTOMATION_SERVICE_USER:-$(stat -c '%U' "$ROOT")}"
[[ -n "$SERVICE_USER" && "$SERVICE_USER" != "UNKNOWN" ]] || fail "Nao foi possivel identificar o usuario do servico."

SYSTEMD_DIR="$ROOT/deploy/systemd"
[[ -f "$SYSTEMD_DIR/automation-api.service" ]] || fail "Template systemd da API nao encontrado."
[[ -f "$SYSTEMD_DIR/automation-worker.service" ]] || fail "Template systemd do worker nao encontrado."

log "Instalando unidades systemd para o usuario $SERVICE_USER."
for service in automation-api automation-worker; do
    rendered="$(mktemp)"
    sed \
        -e "s|@AUTOMATION_USER@|$SERVICE_USER|g" \
        -e "s|@AUTOMATION_ROOT@|$ROOT|g" \
        "$SYSTEMD_DIR/$service.service" > "$rendered"
    as_root install -o root -g root -m 0644 "$rendered" "/etc/systemd/system/$service.service"
    rm -f "$rendered"
done

as_root systemctl daemon-reload
as_root systemctl enable automation-api.service automation-worker.service
as_root systemctl restart automation-api.service automation-worker.service

log "Validando servicos."
as_root systemctl --no-pager --full status automation-api.service automation-worker.service
log "Atualizacao concluida."
