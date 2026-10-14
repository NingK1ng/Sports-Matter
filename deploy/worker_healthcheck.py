"""Healthcheck for a Celery worker; web-server ports do not prove worker health."""
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from core.queue import celery_app

    destination = os.getenv("CELERY_WORKER_NODENAME") or f"celery@{socket.gethostname()}"
    replies = celery_app.control.ping(destination=[destination], timeout=5)
    return 0 if any(reply.get(destination, {}).get("ok") == "pong" for reply in replies) else 1


if __name__ == "__main__":
    raise SystemExit(main())
