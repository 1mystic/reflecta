"""Structured logging — plain for dev, JSON for prod (log aggregators love JSON).

    from reflecta.logging_config import get_logger
    log = get_logger(__name__)
    log.info("quiz_started", extra={"session_id": sid})
"""
from __future__ import annotations

import json
import logging
import sys

from reflecta.config import CONFIG

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # attach any structured extras (skip logging internals)
        std = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        for k, v in record.__dict__.items():
            if k not in std and k != "message":
                base[k] = v
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, default=str)


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    if CONFIG.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s %(name)s  %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(CONFIG.log_level.upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)
