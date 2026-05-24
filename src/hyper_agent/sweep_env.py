from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def apply_env_mapping(env_path: Path, mapping: dict[str, str]) -> Path | None:
    """Apply key/value updates to a dotenv file, creating a timestamped backup first."""
    backup_path: Path | None = None
    content = ""
    if env_path.exists():
        content = env_path.read_text()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = env_path.with_suffix(env_path.suffix + f".{stamp}.bak")
        backup_path.write_text(content)

    lines = content.splitlines()
    seen: set[str] = set()
    for idx, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key in mapping:
            lines[idx] = f"{key}={mapping[key]}"
            seen.add(key)
    for key, value in mapping.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines).rstrip() + "\n")
    return backup_path
