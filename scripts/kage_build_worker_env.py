"""Build the KAGE Telegram content_worker env file: host secrets + committed release flags.

Usage: python -m scripts.kage_build_worker_env --host-env /opt/ai-newsroom/.env \
           --flags deploy/kage_telegram/content_worker.flags.env --out /opt/<release>/content_worker.env

Every key appears exactly once. Committed flags always win over the host env (duplicates in the
host env are collapsed the same way Docker resolves them: the last value wins, then the flag
overrides). The flags file may never carry a secret. Values are never printed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FLAGS_PATH = Path(__file__).resolve().parents[1] / "deploy" / "kage_telegram" / "content_worker.flags.env"
_SECRET_KEY = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASS\b|DSN|CREDENTIAL|HASH", re.IGNORECASE)
_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_env(text: str) -> list[tuple[str, str]]:
    pairs = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            raise ValueError(f"unparseable env line: {line.split('=', 1)[0]!r}")
        pairs.append((match.group(1), match.group(2)))
    return pairs


def load_flags(path: Path = FLAGS_PATH) -> dict[str, str]:
    pairs = parse_env(path.read_text(encoding="utf-8"))
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"release flags define keys more than once: {duplicates}")
    secrets = [key for key in keys if _SECRET_KEY.search(key)]
    if secrets:
        raise ValueError(f"release flags must not carry secrets: {secrets}")
    return dict(pairs)


def build_worker_env(host_env_text: str, flags: dict[str, str]) -> list[str]:
    merged: dict[str, str] = {}
    for key, value in parse_env(host_env_text):
        merged[key] = value  # Docker semantics: last duplicate wins
    merged.update(flags)  # committed release flags always win
    return [f"{key}={value}" for key, value in merged.items()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host-env", required=True, type=Path)
    parser.add_argument("--flags", type=Path, default=FLAGS_PATH)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    flags = load_flags(args.flags)
    lines = build_worker_env(args.host_env.read_text(encoding="utf-8"), flags)
    if args.out.exists():
        print(f"STOP: {args.out} already exists (never overwritten)", file=sys.stderr)
        return 2
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.out.chmod(0o600)
    for key in sorted(flags):
        print(f"{key}={flags[key]}")
    print(f"KEYS={len(lines)} (each exactly once); secrets copied from host env, not printed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
