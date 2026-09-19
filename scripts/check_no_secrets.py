"""Tracked source files에 서울/공공 API key literal이 들어가지 않았는지 검사한다."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_NAMES = (
    "SEOUL_OPEN_DATA_API_KEY",
    "SEOUL_SUBWAY_API_KEY",
    "KOR_TRAVEL_MAP_API_SEOULGOKR_SERVICE_KEY",
    "KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY",
    "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
)
ASSIGNMENT = re.compile(
    r"(?P<name>" + "|".join(map(re.escape, ENV_NAMES)) + r")\s*(?:=|:)\s*"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
)
PLACEHOLDER_PARTS = (
    "<",
    ">",
    "sample",
    "fixture",
    "placeholder",
    "your-",
    "발급키",
    "...",
    "$",
)


def main() -> int:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    violations: list[tuple[str, int, str]] = []
    for raw_path in output.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in ASSIGNMENT.finditer(line):
                value = match.group("value").strip().lower()
                if value and not any(part in value for part in PLACEHOLDER_PARTS):
                    violations.append(
                        (str(path.relative_to(ROOT)), line_number, match.group("name"))
                    )
    if violations:
        for path, line_number, name in violations:
            print(f"secret-like literal: {path}:{line_number} ({name})")
        return 1
    print("no tracked Seoul/public API key literals found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
