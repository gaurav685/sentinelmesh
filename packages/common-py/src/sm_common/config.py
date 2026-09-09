"""Typed runtime configuration (Engineering Constitution §18).

One flat `AppSettings` model, populated from `SM_`-prefixed environment variables
(and an optional `.env` file for local dev). It is validated at construction:
missing required values or an unsafe production combination make the service
refuse to start.

`load_settings()` is the entry point. It is cached — call it once at startup and
pass the object down; do not re-read the environment ad hoc.

Field names map 1:1 to `.env.example` (e.g. `SM_PG_HOST` -> `pg_host`). Grouped
accessors (`.postgres`, `.redis`, ...) return small typed views for callers that
want them.
"""

from __future__ import annotations

import functools
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "AppSettings",
    "Environment",
    "LlmToolMode",
    "OidcView",
    "PostgresView",
    "RedisView",
    "ResponseMode",
    "load_settings",
]


class Environment(StrEnum):
    local = "local"
    ci = "ci"
    staging = "staging"
    production = "production"


class ResponseMode(StrEnum):
    suggest_only = "suggest_only"
    approve_required = "approve_required"
    auto = "auto"


class LlmToolMode(StrEnum):
    constrained = "constrained"
    off = "off"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unknown SM_* vars (e.g. another service's) are not an error
        frozen=True,
        case_sensitive=False,
    )

    # ---- runtime -----------------------------------------------------------
    env: Environment = Environment.local
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    service_name: str = Field(min_length=1, description="Required per service, e.g. 'api-gateway'.")
    deployment_profile: Literal["monolith", "distributed"] = "monolith"

    # ---- postgres --------------------------------------------------------
    pg_host: str = "localhost"
    pg_port: int = Field(default=5432, ge=1, le=65535)
    pg_db: str = "sentinelmesh"
    pg_user: str = "sentinelmesh"
    pg_password: SecretStr = SecretStr("")
    pg_pool_min: int = Field(default=1, ge=0)
    pg_pool_max: int = Field(default=10, ge=1)
    pg_statement_timeout_ms: int = Field(default=15_000, ge=0)

    # ---- neo4j (declared now; unused until Phase 2/3) --------------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = "neo4j"
    neo4j_query_timeout_ms: int = Field(default=10_000, ge=0)

    # ---- kafka (event bus; ADR-008) -----------------------------------
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_security_protocol: Literal["PLAINTEXT", "SASL_PLAINTEXT", "SASL_SSL"] = "PLAINTEXT"
    kafka_consumer_group: str | None = None
    kafka_sasl_username: SecretStr | None = None
    kafka_sasl_password: SecretStr | None = None
    kafka_send_timeout_ms: int = Field(default=10_000, ge=1_000, le=60_000)
    # When true a producing service opens a Kafka producer at startup, probes it
    # in `/readyz`, and its event sinks write to the bus. When false the sinks
    # fall back to a logging stopgap (dev / tests without a broker).
    event_bus_enabled: bool = False

    # ---- redis ----------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    redis_password: SecretStr | None = None
    redis_key_prefix: str = "sm"

    # ---- object store (declared now) ----------------------------------
    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    s3_bucket_artifacts: str = "sm-artifacts"
    s3_bucket_reports: str = "sm-reports"

    # ---- auth / oidc --------------------------------------------------
    oidc_issuer: str = "http://localhost:8080/realms/sentinelmesh"
    oidc_client_id: str = "sentinelmesh-api"
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_audience: str = "sentinelmesh"
    jwt_leeway_seconds: int = Field(default=30, ge=0)
    session_cookie_secure: bool = True
    session_cookie_name: str = "sm_session"
    csrf_cookie_name: str = "sm_csrf"
    session_idle_seconds: int = Field(default=3600, ge=60)
    session_absolute_seconds: int = Field(default=43_200, ge=300)
    oidc_state_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    # Brute-force protection for the local-fallback login path.
    login_max_failures: int = Field(default=10, ge=3)
    login_lockout_seconds: int = Field(default=900, ge=30)

    # ---- service-to-service auth ------------------------------------
    internal_jwt_signing_key: SecretStr = SecretStr("")
    internal_jwt_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    # ---- llm (declared now; unused until Phase 6) -----------------
    llm_default_provider: Literal["anthropic", "openai", "local"] = "anthropic"
    llm_default_model: str | None = None
    llm_request_timeout_s: int = Field(default=60, ge=1)
    llm_tool_mode: LlmToolMode = LlmToolMode.constrained

    # ---- http hardening --------------------------------------------
    http_max_body_bytes: int = Field(default=1_048_576, ge=1)
    http_request_timeout_s: int = Field(default=30, ge=1)
    cors_allowed_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = Field(default=120, ge=1)
    # Number of trusted reverse proxies between the client and this service.
    # 0 (default) means use the direct peer address and ignore X-Forwarded-For
    # entirely, so a client cannot spoof its source IP. Set it to the real hop
    # count only when running behind a known ingress.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)

    # ---- ingestion gateway (Phase 2) ------------------------------
    # A sensor may send `X-Sensor-Event-Id` for at-most-once delivery of a single
    # event; the id is remembered this long in Redis.
    ingest_dedup_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    # Upper bound on `events` in one `POST /api/v1/ingest/batch` call.
    ingest_batch_max_events: int = Field(default=500, ge=1, le=10_000)

    # ---- autonomous response safety ------------------------------
    response_mode: ResponseMode = ResponseMode.suggest_only
    response_approval_required: bool = True
    response_policy_document_path: str | None = None

    # ---- observability -----------------------------------------
    otel_exporter_otlp_endpoint: str | None = None
    otel_traces_enabled: bool = True
    prometheus_metrics_port: int = Field(default=9464, ge=1, le=65535)

    # ---- datasets --------------------------------------------
    dataset_root: str | None = None

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    @model_validator(mode="after")
    def _pool_bounds(self) -> AppSettings:
        if self.pg_pool_max < self.pg_pool_min:
            raise ValueError("SM_PG_POOL_MAX must be >= SM_PG_POOL_MIN")
        if self.session_absolute_seconds < self.session_idle_seconds:
            raise ValueError("SM_SESSION_ABSOLUTE_SECONDS must be >= SM_SESSION_IDLE_SECONDS")
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> AppSettings:
        if self.env is not Environment.production:
            return self

        problems: list[str] = []
        if "*" in self.cors_origins_list:
            problems.append("SM_CORS_ALLOWED_ORIGINS must not contain '*' in production")
        if not self.session_cookie_secure:
            problems.append("SM_SESSION_COOKIE_SECURE must be true in production")
        for name, secret in (
            ("SM_PG_PASSWORD", self.pg_password),
            ("SM_INTERNAL_JWT_SIGNING_KEY", self.internal_jwt_signing_key),
            ("SM_OIDC_CLIENT_SECRET", self.oidc_client_secret),
        ):
            if not secret.get_secret_value():
                problems.append(f"{name} is required in production")
        if self.response_mode is ResponseMode.auto:
            if not self.response_policy_document_path:
                problems.append(
                    "SM_RESPONSE_MODE=auto requires SM_RESPONSE_POLICY_DOCUMENT_PATH"
                )
        if self.kafka_security_protocol != "SASL_SSL":
            problems.append("SM_KAFKA_SECURITY_PROTOCOL must be SASL_SSL in production")

        if problems:
            raise ValueError(
                "unsafe production configuration:\n  - " + "\n  - ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def _response_auto_needs_production(self) -> AppSettings:
        if self.response_mode is ResponseMode.auto and self.env is not Environment.production:
            raise ValueError("SM_RESPONSE_MODE=auto is only permitted when SM_ENV=production")
        return self

    # ------------------------------------------------------------------ #
    # derived accessors
    # ------------------------------------------------------------------ #
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env is Environment.production

    @property
    def pg_dsn(self) -> str:
        """asyncpg-style DSN. Password is included (this is used to open the
        connection, never logged)."""
        pw = self.pg_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.pg_user}:{pw}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def postgres(self) -> PostgresView:
        return PostgresView(
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_db,
            user=self.pg_user,
            pool_min=self.pg_pool_min,
            pool_max=self.pg_pool_max,
            statement_timeout_ms=self.pg_statement_timeout_ms,
            dsn=self.pg_dsn,
        )

    @property
    def redis(self) -> RedisView:
        return RedisView(url=self.redis_url, key_prefix=self.redis_key_prefix)

    @property
    def oidc(self) -> OidcView:
        return OidcView(
            issuer=self.oidc_issuer,
            client_id=self.oidc_client_id,
            audience=self.oidc_audience,
            leeway_seconds=self.jwt_leeway_seconds,
        )


class PostgresView(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str
    port: int
    database: str
    user: str
    pool_min: int
    pool_max: int
    statement_timeout_ms: int
    dsn: str


class RedisView(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    key_prefix: str

    def key(self, *parts: str) -> str:
        return ":".join((self.key_prefix, *parts))


class OidcView(BaseModel):
    model_config = ConfigDict(frozen=True)
    issuer: str
    client_id: str
    audience: str
    leeway_seconds: int


@functools.lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    """Construct and cache `AppSettings`. Raises `pydantic.ValidationError` on a
    missing required value or an unsafe production combination."""
    return AppSettings()  # values come from env / .env


def _reset_cache_for_tests() -> None:
    load_settings.cache_clear()
