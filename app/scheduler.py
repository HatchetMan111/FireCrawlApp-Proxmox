import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import CHECK_INTERVAL_MINUTES, TIMEZONE
from .services import check_due_products

scheduler = BackgroundScheduler(timezone=TIMEZONE)


def run_due_checks() -> None:
    asyncio.run(check_due_products())


def start() -> None:
    if scheduler.get_job("price_check_loop"):
        return
    scheduler.add_job(
        run_due_checks,
        IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES, timezone=TIMEZONE),
        id="price_check_loop",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def next_run() -> str | None:
    job = scheduler.get_job("price_check_loop")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
