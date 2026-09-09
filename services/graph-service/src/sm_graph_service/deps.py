"""Dependency wiring for graph-service. The HTTP surface is health / metrics
only; the work happens in the consumer loop the lifespan owns."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from sm_common.bus import EventBusConsumer, EventBusProducer, RecordProcessor
from sm_common.config import AppSettings
from sm_common.graph import Graph
from sm_common.observability import Metrics

from .engine import GraphEngine
from .metrics import GraphMetrics

__all__ = ["Services", "get_services"]


@dataclass
class Services:
    settings: AppSettings
    metrics: Metrics
    graph_metrics: GraphMetrics
    graph: Graph
    producer: EventBusProducer
    consumer: EventBusConsumer
    engine: GraphEngine
    processor: RecordProcessor


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services
