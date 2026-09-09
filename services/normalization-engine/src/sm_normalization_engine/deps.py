"""Dependency wiring for the normalization engine.

`Services` is built once at startup. There is no request-scoped dependency — the
only HTTP surface is health / metrics; the work happens in the consumer loop the
lifespan owns.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from sm_common.bus import EventBusConsumer, EventBusProducer
from sm_common.config import AppSettings
from sm_common.observability import Metrics

from .engine import NormalizationEngine
from .metrics import NormalizationMetrics

__all__ = ["Services", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    norm_metrics: NormalizationMetrics
    producer: EventBusProducer
    consumer: EventBusConsumer
    engine: NormalizationEngine


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services
