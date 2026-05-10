#!/usr/bin/env bash
set -euo pipefail

command -v tailscale >/dev/null || { echo "tailscale not found"; exit 1; }

# Tailscale Serve keeps this private to your tailnet.
# Do not use `tailscale funnel` for this trading dashboard.
tailscale serve --bg localhost:8765
tailscale serve status

