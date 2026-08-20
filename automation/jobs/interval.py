from __future__ import annotations

from apscheduler.triggers.interval import IntervalTrigger


def register_interval_job(
    scheduler,
    callback,
    timezone: str,
    interval_seconds: int,
    *args,
) -> None:
    if hasattr(callback, "run_job") and len(args) == 2:
        scheduler.add_job(
            callback.run_job,
            IntervalTrigger(seconds=interval_seconds, timezone=timezone),
            kwargs={
                "site_name": args[0],
                "report_name": args[1],
                "filters": {},
            },
            id=f"{args[0]}:{args[1]}:interval",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        return

    scheduler.add_job(
        callback,
        IntervalTrigger(seconds=interval_seconds, timezone=timezone),
        args=args,
        id=":".join([str(arg) for arg in args]) + ":interval",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
