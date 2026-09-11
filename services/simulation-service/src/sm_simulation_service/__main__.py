"""Run simulation-service: `python -m sm_simulation_service`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings

from .version import DEFAULT_PORT


def main() -> None:
    load_settings()
    uvicorn.run(
        "sm_simulation_service.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=DEFAULT_PORT,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
