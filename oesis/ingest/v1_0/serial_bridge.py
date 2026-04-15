#!/usr/bin/env python3
"""Forward bench-air JSON lines from a USB serial port to the local ingest HTTP API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http import HTTPStatus
from typing import Any

BENCH_AIR_SCHEMA = "oesis.bench-air.v1"
CIRCUIT_MONITOR_SCHEMA = "oesis.circuit-monitor.v1"
FLOOD_NODE_SCHEMA = "oesis.flood-node.v1"
WEATHER_PM_MAST_SCHEMA = "oesis.weather-pm-mast.v1"
ACCEPTED_SCHEMAS = {BENCH_AIR_SCHEMA, CIRCUIT_MONITOR_SCHEMA, FLOOD_NODE_SCHEMA, WEATHER_PM_MAST_SCHEMA}
DEFAULT_INGEST_PATH = "/v1/ingest/node-packets"


def _require_serial():
    try:
        import serial  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit(
            "pyserial is required for the serial bridge. "
            "Install with: pip install 'oesis-runtime[serial-bridge]'"
        ) from exc
    return serial


def parse_packet_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def post_ingest(
    *,
    url: str,
    parcel_id: str,
    packet: dict[str, Any],
    timeout_s: float,
) -> tuple[int, dict[str, Any] | None]:
    body = json.dumps(packet, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-OESIS-Parcel-Id", parcel_id)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
            try:
                return status, json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                return status, None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            parsed = None
        return int(exc.code), parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read oesis.bench-air.v1 JSON lines from a serial port and POST each packet "
            "to the reference ingest API (same contract as curl in oesis-http-check)."
        ),
    )
    parser.add_argument(
        "--serial-port",
        required=True,
        help="Serial device path (e.g. /dev/cu.usbmodem101 on macOS, COM3 on Windows).",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Serial baud rate (default: 115200).",
    )
    parser.add_argument(
        "--ingest-base",
        default="http://127.0.0.1:8787",
        help="Ingest API base URL without trailing slash (default: http://127.0.0.1:8787).",
    )
    parser.add_argument(
        "--ingest-path",
        default=DEFAULT_INGEST_PATH,
        help=f"Ingest POST path (default: {DEFAULT_INGEST_PATH}).",
    )
    parser.add_argument(
        "--parcel-id",
        default="parcel_demo_001",
        help="Parcel id sent as X-OESIS-Parcel-Id (default: parcel_demo_001).",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=15.0,
        help="HTTP request timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--no-schema-check",
        action="store_true",
        help="Accept any JSON object on a line (not recommended).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Post the first valid packet and exit successfully.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate packets only; do not POST.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-packet success lines; still print errors.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    serial = _require_serial()

    ingest_url = args.ingest_base.rstrip("/") + args.ingest_path
    strict_schema = not args.no_schema_check

    try:
        ser = serial.Serial(args.serial_port, args.baud, timeout=1)
    except OSError as exc:
        print(f"ERROR: could not open serial port {args.serial_port!r}: {exc}", file=sys.stderr)
        return 1

    posted = 0
    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            packet = parse_packet_line(line)
            if packet is None:
                continue
            if strict_schema:
                schema_match = (
                    packet.get("schema_version") in ACCEPTED_SCHEMAS
                    or packet.get("schema_id") in ACCEPTED_SCHEMAS
                )
                if not schema_match:
                    if not args.quiet:
                        found = packet.get("schema_version") or packet.get("schema_id") or "?"
                        print(
                            f"SKIP: schema {found!r} not in {sorted(ACCEPTED_SCHEMAS)}",
                            file=sys.stderr,
                        )
                    continue

            if args.dry_run:
                if not args.quiet:
                    node = packet.get("node_id", "?")
                    print(f"DRY-RUN ok node_id={node}", flush=True)
                posted += 1
                if args.once:
                    break
                continue

            status, body = post_ingest(
                url=ingest_url,
                parcel_id=args.parcel_id,
                packet=packet,
                timeout_s=args.http_timeout,
            )
            if status != HTTPStatus.ACCEPTED:
                detail = ""
                if body and isinstance(body.get("detail"), str):
                    detail = f": {body['detail']}"
                elif body:
                    detail = f": {body!r}"
                print(f"ERROR: ingest HTTP {status}{detail}", file=sys.stderr)
                return 1

            posted += 1
            if not args.quiet:
                node = packet.get("node_id", "?")
                obs = (body or {}).get("normalized_observation", {}) if body else {}
                oid = obs.get("observation_id", "?")
                print(f"OK posted observation_id={oid} node_id={node}", flush=True)

            if args.once:
                break
    except KeyboardInterrupt:
        if not args.quiet and posted:
            print(f"Stopped after {posted} packet(s).", file=sys.stderr)
        return 0
    finally:
        ser.close()

    if args.once and posted == 0:
        print("ERROR: no valid packet received before end of stream.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
