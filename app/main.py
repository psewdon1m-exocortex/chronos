from __future__ import annotations

import logging

import uvicorn

from .config import load_config


def run() -> None:
    config = load_config()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=config.listen_port,
        proxy_headers=config.trust_proxy,
        forwarded_allow_ips="*" if config.trust_proxy else "127.0.0.1",
        access_log=True,
    )


if __name__ == "__main__":
    run()

