"""
Centralized structured logging — JSON Lines to stdout only, never to a file.

Containers stay stateless: nothing is persisted to local disk. Each log line is a
single JSON object on stdout, which Docker already captures via its `json-file` log
driver. The optional Filebeat sidecar (see docker-compose.logging.yml) tails those
container logs and ships them to Elasticsearch — the app itself has zero dependency
on or awareness of Elasticsearch; remove the sidecar and the app behaves identically.

Used by both entry points that can be the process root:
  backend/app/main.py   (embedded mode — also covers agents/ when they run in-process)
  agents/main.py         (standalone mode — AGENTS_STANDALONE=true, separate container)
"""

import logging
import sys

import structlog


def configure_logging(service: str) -> None:
    """Call once, as early as possible in the process, before any log call."""

    def _add_service(_logger, _method_name, event_dict: dict) -> dict:
        event_dict["service"] = service
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_service,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, asyncio warnings, ...) through the
    # same stdout stream instead of their own default handlers — one log source per
    # container, no separate files, nothing for the Filebeat sidecar to miss.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
