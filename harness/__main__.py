from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from harness.config.init import run_init

        run_init()
        return

    from harness.main import start_agent

    try:
        asyncio.run(start_agent(continue_session="--continue" in sys.argv[1:]))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
