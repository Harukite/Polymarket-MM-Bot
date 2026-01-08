#!/usr/bin/env bash
set -euo pipefail
pmm db init
pmm universe refresh
pmm run paper
