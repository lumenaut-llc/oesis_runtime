"""Entry point for `python3 -m oesis`."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        """oesis — Open Environmental Sensing and Inference System

Available subcommands:

  python3 -m oesis.parcel_platform.reference_pipeline   Run the reference pipeline (packet → parcel view)
  python3 -m oesis.checks                               Run offline acceptance checks
  python3 -m oesis.checks --help                        Show acceptance check options
  python3 -m oesis.ingest.serve_ingest_api              Start the local ingest HTTP service
  python3 -m oesis.ingest.serial_bridge                 Forward serial node packets to ingest API
  python3 -m oesis.ingest.validate_examples             Validate packaged example JSON
  python3 -m oesis.common.runtime_lane                  Materialize lane asset overrides

Or use Make:

  make help                                             Show all available targets
  make oesis-demo                                       Run the reference pipeline
  make oesis-check                                      Validate + demo + verify output shape"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
