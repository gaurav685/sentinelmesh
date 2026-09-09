"""Run the ingestion gateway with uvicorn: `python -m sm_ingestion_gateway`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings


def main() -> None:
    # Validate configuration before uvicorn binds a port.
    load_settings()

    uvicorn.run(
        "sm_ingestion_gateway.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=8001,
        log_config=None,  # structlog owns logging
        access_log=False,  # RequestContextMiddleware emits the access line
    )


if __name__ == "__main__":
    main()
