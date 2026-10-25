"""Install Filedrop in a private local virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    prefix = Path(
        os.environ.get("FILEDROP_INSTALL_PREFIX", "~/.local/share/filedrop")
    ).expanduser().resolve()
    bin_dir = Path(os.environ.get("FILEDROP_BIN_DIR", "~/.local/bin")).expanduser()
    bin_dir.mkdir(parents=True, exist_ok=True)
    environment = prefix / "venv"

    if not (environment / "pyvenv.cfg").is_file():
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
    python = environment / "bin" / "python"
    executable = environment / "bin" / "filedrop"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-build-isolation",
            "--no-deps",
            "--force-reinstall",
            str(Path(__file__).resolve().parent),
        ],
        check=True,
    )

    launcher = bin_dir / "filedrop"
    temporary_launcher = bin_dir / f".filedrop-{os.getpid()}"
    try:
        temporary_launcher.symlink_to(executable)
        temporary_launcher.replace(launcher)
    finally:
        temporary_launcher.unlink(missing_ok=True)

    print(f"Installed Filedrop: {launcher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
