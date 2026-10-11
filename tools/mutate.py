"""We break the code on purpose and watch whether the tests go red. A watchman who never
goes red is no watchman.

    python3 tools/mutate.py breakages.json

The file is a list of breakages: [{"file": "lan_map/roads.py", "old": "...", "new": "...",
"what": "..."}]. They are applied one at a time, the tests are run, and the file is put back.

Bytecode is switched off on purpose: a replacement of equal length within the same second
leaves the old .pyc, and then the tests check something other than what is on disk. We have
been caught by that once already.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def run_tests() -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                          capture_output=True, text=True, cwd=BASE, env=env)


def failures(done: subprocess.CompletedProcess) -> list:
    return sorted({line.split("(")[0].removeprefix("FAIL: ").removeprefix("ERROR: ").strip()
                   for line in done.stderr.splitlines() if line.startswith(("FAIL:", "ERROR:"))})


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    breakages = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    green = run_tests()
    if green.returncode:
        print("the tests are red before any breakage — fix them first")
        print("\n".join(failures(green)))
        return 1
    survived = 0
    for breakage in breakages:
        file = BASE / breakage["file"]
        saved = file.read_text(encoding="utf-8")
        seen = saved.count(breakage["old"])
        if seen != 1:
            print(f"{breakage['what']}: the piece occurs {seen} times — the breakage did not apply")
            survived += 1
            continue
        file.write_text(saved.replace(breakage["old"], breakage["new"]), encoding="utf-8")
        try:
            done = run_tests()
        finally:
            file.write_text(saved, encoding="utf-8")
        if done.returncode:
            print(f"RED    {breakage['what']}: {', '.join(failures(done)[:3])}")
        else:
            print(f"GREEN  {breakage['what']}: nobody noticed the breakage")
            survived += 1
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
