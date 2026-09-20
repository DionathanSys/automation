from __future__ import annotations

from pathlib import Path


def upgrade_database() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise RuntimeError(
            "Alembic nao instalado. Execute pip install -r requirements.txt."
        ) from exc

    project_root = Path(__file__).resolve().parents[2]
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "migrations"))
    command.upgrade(alembic_config, "head")
