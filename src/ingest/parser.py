from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Generator, Iterable, Optional


# Normalized keys we expose downstream
NORMAL_KEYS = {
    "ts": ["timestamp", "ts", "time", "datetime", "@timestamp"],
    "source": ["source", "service", "component", "logger", "app"],
    "message": ["message", "msg", "log", "text"],
    "channel": ["channel", "topic", "stream", "facility"],
}


def _first_present(d: Dict[str, Any], candidates: list[str]) -> Optional[Any]:
    for c in candidates:
        if c in d:
            return d[c]
    # try case-insensitive
    lower = {k.lower(): v for k, v in d.items()}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def normalize_event(obj: Any) -> Dict[str, Any]:
    """Normalize any event (dict or string) into a dict with keys ts, source, message, channel, raw."""
    if isinstance(obj, dict):
        ts = _first_present(obj, NORMAL_KEYS["ts"]) or ""
        source = _first_present(obj, NORMAL_KEYS["source"]) or obj.get("source", "")
        message = _first_present(obj, NORMAL_KEYS["message"]) or obj.get("message", "")
        channel = _first_present(obj, NORMAL_KEYS["channel"]) or obj.get("channel", "")
        return {"ts": str(ts), "source": str(source), "message": str(message), "channel": str(channel), "raw": obj}
    # try JSON line
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                d = json.loads(s)
                return normalize_event(d)
            except Exception:
                pass
        # fallback: just pass through
        return {"ts": "", "source": "", "message": s, "channel": "", "raw": obj}
    # unknown type
    return {"ts": "", "source": "", "message": str(obj), "channel": "", "raw": obj}


def read_file_stream(path: str) -> Generator[Dict[str, Any], None, None]:
    """Yield normalized events from a dataset file.

    Supported formats:
    - JSON Lines (one JSON object per line)
    - CSV/TSV with header containing some of: timestamp/ts/time, source, message, channel
    - If header missing, assumes columns: timestamp, source, message, channel
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "r", encoding="utf-8", newline="") as f:
        # Peek to detect format
        first = f.readline()
        if not first:
            return

        # JSON lines
        if first.strip().startswith("{"):
            try:
                d = json.loads(first)
                yield normalize_event(d)
            except Exception:
                # If malformed JSON, treat as CSV below
                pass
            else:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        yield normalize_event(d)
                    except Exception:
                        yield normalize_event(line)
                return

        # CSV/TSV
        # Rewind to start to include first line for DictReader
        f.seek(0)
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except Exception:
            # default to comma
            dialect = csv.get_dialect("excel")

        reader = csv.reader(f, dialect)
        try:
            header = next(reader)
        except StopIteration:
            return
        if not header:
            header = ["timestamp", "source", "message", "channel"]

        # Build DictReader-like rows
        for row in reader:
            if not row:
                continue
            d = {header[i]: row[i] for i in range(min(len(header), len(row)))}
            yield normalize_event(d)
