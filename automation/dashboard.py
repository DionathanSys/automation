"""Read-only operational dashboard backed by the automation database and Redis."""

from __future__ import annotations

import html
import json
import secrets
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from automation.config import settings
from automation.db.schema import (
    clients_table, events_table, job_attempts_table, job_results_table,
    jobs_table, system_state_table, webhook_deliveries_table,
)

basic = HTTPBasic()
STYLE = """
:root{font-family:system-ui,sans-serif;color:#e5edf6;background:#101827}
*{box-sizing:border-box}body{margin:0}header{background:#172235;padding:18px 4%;border-bottom:1px solid #34445c}
main{max-width:1450px;margin:auto;padding:25px 4%}a{color:#8dd1ff;text-decoration:none}a:hover{text-decoration:underline}
nav{display:flex;gap:20px;align-items:center}h1{font-size:1.5rem;margin:0 0 8px}h2{font-size:1.15rem;margin:24px 0 10px}
.muted{color:#a9b8c9}.cards{display:flex;flex-wrap:wrap;gap:12px}.card,.panel{background:#1a283b;border:1px solid #34445c;border-radius:10px;padding:15px}
.card{min-width:145px}.card strong{display:block;font-size:1.6rem}.panel{margin:15px 0;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:.91rem}th,td{text-align:left;padding:9px;border-bottom:1px solid #34445c;vertical-align:top}
th{color:#b9c9da}code,pre{font-family:ui-monospace,SFMono-Regular,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
input,select,button{background:#111c2c;color:#e5edf6;border:1px solid #4a5e76;border-radius:6px;padding:8px}
form{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.badge{border-radius:30px;padding:3px 8px;background:#34445c}
.COMPLETED,.RUNNING{background:#165442}.FAILED,.CANCELLED{background:#793942}.QUEUED,.RETRYING{background:#6a5628}
.alert{border-left:4px solid #e8a14d;padding:10px;background:#342c26}.pages{display:flex;gap:16px;margin-top:14px}
"""


def esc(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M:%S UTC")
    return html.escape(str(value), quote=True)


def pretty(value: object) -> str:
    return esc(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def page(title: str, body: str) -> HTMLResponse:
    content = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{esc(title)} · Automation</title><style>{STYLE}</style></head><body>
<header><nav><strong>Automation</strong><a href="/dashboard">Visão geral</a><a href="/dashboard/jobs">Jobs</a></nav></header>
<main><h1>{esc(title)}</h1><p class="muted">Somente leitura · dados do MySQL e Redis · horários do banco em UTC</p>{body}</main></body></html>"""
    return HTMLResponse(content, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{esc(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">Nenhum registro encontrado.</td></tr>'
    return f'<div class="panel"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def install_dashboard(app, engine: Engine) -> None:
    """Disabled unless a dedicated dashboard login and password are configured."""
    username = settings.api.dashboard_username
    password = settings.api.dashboard_password
    if not username or not password:
        return

    def authenticate(credentials: HTTPBasicCredentials = Depends(basic)) -> None:
        valid = secrets.compare_digest(credentials.username.encode(), username.encode())
        valid &= secrets.compare_digest(credentials.password.encode(), password.encode())
        if not valid:
            raise HTTPException(401, "Credenciais invalidas", headers={"WWW-Authenticate": 'Basic realm="Automation dashboard"'})

    router = APIRouter(prefix="/dashboard", dependencies=[Depends(authenticate)], include_in_schema=False)

    @router.get("", response_class=HTMLResponse)
    def overview() -> HTMLResponse:
        with engine.connect() as db:
            counts = dict(db.execute(select(jobs_table.c.status, func.count()).group_by(jobs_table.c.status)).all())
            state = db.execute(select(system_state_table.c.mode).where(system_state_table.c.id == "global")).scalar_one_or_none() or "RUNNING"
            recent = db.execute(select(jobs_table.c.id, jobs_table.c.collector, jobs_table.c.status, jobs_table.c.result_count, jobs_table.c.requested_at).order_by(jobs_table.c.requested_at.desc()).limit(12)).all()
            pending_webhooks = db.execute(select(func.count()).select_from(webhook_deliveries_table).where(webhook_deliveries_table.c.status.in_(["DELIVERING", "RETRYING"]))).scalar_one()

        redis_status = "indisponível"
        redis_queues: list[tuple[str, int]] = []
        try:
            from redis import Redis
            redis = Redis.from_url(settings.queue.redis_url, socket_connect_timeout=2, socket_timeout=2)
            redis.ping()
            redis_status = "conectado"
            # Inspect actual Redis lists under this broker's namespace; never infer worker liveness.
            for key in redis.scan_iter(match=f"{settings.queue.queue_name}:*", count=100):
                if len(redis_queues) >= 100:
                    break
                if redis.type(key) == b"list":
                    redis_queues.append((key.decode("utf-8", errors="replace"), redis.llen(key)))
        except Exception:
            pass

        cards = [("Modo", state), ("Redis", redis_status), ("Webhooks pendentes", pending_webhooks)] + sorted(counts.items())
        body = '<div class="cards">' + "".join(f'<div class="card">{esc(label)}<strong>{esc(value)}</strong></div>' for label, value in cards) + '</div>'
        body += '<h2>Fila Redis</h2>'
        body += table(["Fila", "Mensagens aguardando"], [[esc(q), esc(n)] for q, n in redis_queues])
        body += '<p class="muted">Os contadores do MySQL representam estados dos jobs; a fila Redis representa mensagens aguardando consumo. Jobs em execução não aparecem na lista pendente.</p>'
        body += '<h2>Jobs recentes</h2>' + jobs_table_html(recent)
        return page("Visão geral", body)

    def jobs_table_html(rows) -> str:
        return table(["Solicitado (UTC)", "Job", "Collector", "Status", "Resultados"], [
            [esc(row.requested_at), f'<a href="/dashboard/jobs/{quote(row.id, safe="")}"><code>{esc(row.id)}</code></a>', esc(row.collector), f'<span class="badge {esc(row.status)}">{esc(row.status)}</span>', esc(row.result_count)] for row in rows
        ])

    @router.get("/jobs", response_class=HTMLResponse)
    def jobs(status: str = "", collector: str = "", page_number: int = Query(1, ge=1, le=10000)) -> HTMLResponse:
        conditions = []
        if status:
            conditions.append(jobs_table.c.status == status.upper()[:30])
        if collector:
            conditions.append(jobs_table.c.collector == collector[:150])
        with engine.connect() as db:
            total = db.execute(select(func.count()).select_from(jobs_table).where(*conditions)).scalar_one()
            rows = db.execute(select(jobs_table.c.id, jobs_table.c.collector, jobs_table.c.status, jobs_table.c.result_count, jobs_table.c.requested_at).where(*conditions).order_by(jobs_table.c.requested_at.desc(), jobs_table.c.id.desc()).offset((page_number - 1) * 50).limit(50)).all()
        form = f'''<form method="get"><label>Status<br><select name="status"><option value="">Todos</option>'''
        for item in ("QUEUED", "RUNNING", "RETRYING", "COMPLETED", "FAILED", "CANCELLED"):
            form += f'<option value="{item}" {"selected" if status.upper() == item else ""}>{item}</option>'
        form += f'</select></label><label>Collector<br><input name="collector" value="{esc(collector)}"></label><button>Filtrar</button></form>'
        body = form + f'<p>{total} jobs encontrados · página {page_number}</p>' + jobs_table_html(rows)
        base = f'/dashboard/jobs?status={quote(status)}&collector={quote(collector)}&page_number='
        body += '<div class="pages">' + (f'<a href="{base}{page_number-1}">← Anterior</a>' if page_number > 1 else '') + (f'<a href="{base}{page_number+1}">Próxima →</a>' if page_number * 50 < total else '') + '</div>'
        return page("Jobs", body)

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(job_id: str, result_page: int = Query(1, ge=1, le=10000)) -> HTMLResponse:
        with engine.connect() as db:
            job = db.execute(select(jobs_table, clients_table.c.code.label("client_code")).join(clients_table, jobs_table.c.client_id == clients_table.c.id, isouter=True).where(jobs_table.c.id == job_id)).mappings().first()
            if job is None:
                raise HTTPException(404, "Job nao encontrado")
            attempts = db.execute(select(job_attempts_table).where(job_attempts_table.c.job_id == job_id).order_by(job_attempts_table.c.attempt_number)).mappings().all()
            events = db.execute(select(events_table.c.event_id, events_table.c.event_type, events_table.c.occurred_at).where(events_table.c.job_id == job_id).order_by(events_table.c.occurred_at)).all()
            event_ids = [row.event_id for row in events]
            deliveries = db.execute(select(webhook_deliveries_table).where(webhook_deliveries_table.c.event_id.in_(event_ids)).order_by(webhook_deliveries_table.c.started_at)).mappings().all() if event_ids else []
            stored_count = db.execute(select(func.coalesce(func.sum(job_results_table.c.record_count), 0)).where(job_results_table.c.job_id == job_id)).scalar_one()
            results = db.execute(select(job_results_table.c.sequence, job_results_table.c.payload_json).where(job_results_table.c.job_id == job_id).order_by(job_results_table.c.sequence).offset(result_page-1).limit(1)).first()
            page_count = db.execute(select(func.count()).select_from(job_results_table).where(job_results_table.c.job_id == job_id)).scalar_one()
        info = [("Cliente", job["client_code"]), ("Collector", job["collector"]), ("Status", job["status"]), ("Resultados declarados", job["result_count"]), ("Registros armazenados", stored_count), ("Solicitado", job["requested_at"]), ("Iniciado", job["started_at"]), ("Terminado", job["finished_at"]), ("Tentativas", f'{job["attempts"]}/{job["max_attempts"]}'), ("Erro", job["error_message"])]
        body = table(["Campo", "Valor"], [[esc(k), esc(v)] for k, v in info])
        body += '<h2>Parâmetros recebidos</h2><div class="panel"><pre>' + pretty(job["parameters_json"]) + '</pre></div>'
        body += '<h2>Metadados</h2><div class="panel"><pre>' + pretty(job["metadata_json"]) + '</pre></div>'
        body += '<h2>Resultados gravados</h2>'
        if results:
            body += f'<p>Página armazenada {result_page} de {page_count} · sequência {results.sequence} · {len(results.payload_json)} registros</p><div class="panel"><pre>{pretty(results.payload_json)}</pre></div>'
            base = f'/dashboard/jobs/{quote(job_id, safe="")}?result_page='
            body += '<div class="pages">' + (f'<a href="{base}{result_page-1}">← Anterior</a>' if result_page > 1 else '') + (f'<a href="{base}{result_page+1}">Próxima →</a>' if result_page < page_count else '') + '</div>'
        else:
            body += '<p class="muted">Nenhum resultado armazenado nesta página.</p>'
        body += '<h2>Tentativas do worker</h2>' + table(["#", "Status", "Início", "Fim", "Erro"], [[esc(a["attempt_number"]), esc(a["status"]), esc(a["started_at"]), esc(a["finished_at"]), esc(a["error_message"])] for a in attempts])
        body += '<h2>Eventos</h2>' + table(["Evento", "Tipo", "Ocorrência"], [[esc(e.event_id), esc(e.event_type), esc(e.occurred_at)] for e in events])
        body += '<h2>Entregas de webhook</h2>' + table(["Evento", "Tentativa", "Status", "HTTP", "Resposta"], [[esc(d["event_id"]), esc(d["attempt_number"]), esc(d["status"]), esc(d["http_status"]), esc(d["response_excerpt"])] for d in deliveries])
        return page(f"Job {job_id}", body)

    app.include_router(router)
