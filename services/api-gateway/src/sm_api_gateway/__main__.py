"""Run the API gateway with uvicorn: `python -m sm_api_gateway`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings


def main() -> None:
    # Load (and therefore validate) configuration before uvicorn binds a port, so
    # a bad or unsafe configuration fails fast with a clear message instead of
    # after the server is already accepting traffic.
    load_settings()

    uvicorn.run(
        "sm_api_gateway.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure is controlled by network policy
        port=8000,
        log_config=None,  # structlog owns logging
        access_log=False,  # RequestContextMiddleware emits the access line
    )


if __name__ == "__main__":
    main()
