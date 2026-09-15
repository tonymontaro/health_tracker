"""Use the SDK's pinned Codex runtime without depending on the shell PATH."""

import os
import subprocess

from codex_cli_bin import bundled_codex_path


def main() -> None:
    action = os.environ.get("HEALTH_CODEX_ACTION", "status")
    if action not in {"login", "status"}:
        raise SystemExit("HEALTH_CODEX_ACTION must be login or status")
    command = [str(bundled_codex_path()), "login"]
    if action == "status":
        command.append("status")
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
