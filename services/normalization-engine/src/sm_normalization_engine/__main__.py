"""Run the normalization engine: `python -m sm_normalization_engine`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings


def main() -> None:
    load_settings()  # validate config before binding a port
    uvicorn.run(
        "sm_normalization_engine.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=8002,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
