"""Run ai-analyst: `python -m sm_ai_analyst`."""

from __future__ import annotations

import uvicorn

from sm_common.config import load_settings

from .version import DEFAULT_PORT


def main() -> None:
    load_settings()
    uvicorn.run(
        "sm_ai_analyst.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - containerised; exposure controlled by network policy
        port=DEFAULT_PORT,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
