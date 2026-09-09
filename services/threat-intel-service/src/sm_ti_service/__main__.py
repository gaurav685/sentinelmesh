"""Run threat-intel-service: `python -m sm_ti_service`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings


def main() -> None:
    load_settings()
    uvicorn.run(
        "sm_ti_service.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=8007,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
