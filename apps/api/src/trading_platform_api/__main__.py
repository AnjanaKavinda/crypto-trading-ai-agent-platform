"""Run the personal API only on an explicit loopback address."""

from __future__ import annotations

import argparse

from trading_platform_api.spot_research import validate_loopback_host


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local research API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    try:
        host = validate_loopback_host(arguments.host)
    except ValueError as exc:
        parser.error(str(exc))
    if type(arguments.port) is not int or not 1 <= arguments.port <= 65535:
        parser.error("--port must be between 1 and 65535.")

    import uvicorn

    uvicorn.run(
        "trading_platform_api.main:app",
        host=host,
        port=arguments.port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
