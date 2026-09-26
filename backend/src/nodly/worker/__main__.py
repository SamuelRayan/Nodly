"""Entry point: python -m nodly.worker

Ctrl+C once: stop claiming and let running jobs finish (up to WORKER_SHUTDOWN_GRACE_SECONDS).
Ctrl+C twice: cancel running jobs now (each is recorded as a failed attempt and retried).
"""

import asyncio
import logging
import signal

import nodly.jobs.handlers  # noqa: F401  # registers every handler and periodic task
from nodly.config import Settings, get_settings
from nodly.db import create_engine, create_sessionmaker
from nodly.jobs.registry import PERIODIC
from nodly.log import configure_logging
from nodly.worker.runner import Worker

logger = logging.getLogger("nodly.worker")


async def serve(settings: Settings) -> None:
    engine = create_engine(settings)
    worker = Worker(settings, create_sessionmaker(engine), periodic=PERIODIC)
    stop, force = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        if stop.is_set():
            logger.warning("second interrupt: cancelling running jobs")
            force.set()
        else:
            logger.info("shutting down; press Ctrl+C again to cancel running jobs")
            stop.set()

    # loop.add_signal_handler() isn't available on Windows, so use signal.signal and hop back
    # onto the loop (no logging or awaiting inside the raw signal handler).
    def on_signal(signum: int, frame: object) -> None:
        loop.call_soon_threadsafe(request_stop)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    try:
        await worker.run(stop, force)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
