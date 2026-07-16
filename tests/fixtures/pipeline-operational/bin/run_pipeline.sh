#!/usr/bin/env bash
set -euo pipefail
bash scripts/report_proxied_domains.sh
python3 scripts/sync_oracle_from_csv.py output/cloudflare.csv
