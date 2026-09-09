"""Run correlation-engine: `python -m sm_correlation_engine`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings


def main() -> None:
    load_settings()
    uvicorn.run(
        "sm_correlation_engine.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=8009,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
