"""Dependency wiring for detection-engine. HTTP surface is health / metrics only;
the work happens in the consumer loop the lifespan owns."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings
from sm_common.db import Database
from sm_common.observability import Metrics

from .engine import DetectionEngine
from .metrics import DetectionMetrics

__all__ = ["Services", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    detection_metrics: DetectionMetrics
    db: Database
    producer: EventBusProducer
    consumer: EventBusConsumer
    engine: DetectionEngine
    processor: RecordProcessor


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services
