"""``python -m keeperkit.server`` — convenience launcher for the demo."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("KEEPERKIT_HOST", "0.0.0.0")
    port = int(os.environ.get("KEEPERKIT_PORT", "8000"))
    uvicorn.run("keeperkit.server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
