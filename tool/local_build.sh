#!/usr/bin/env bash
# Builds one compiler on this Linux machine (or WSL), the way CI does.
#
#   tool/local_build.sh <flutter version> <release|profile> [jobs]
#
# Work files go to ~/xc/work (kept between runs: a second run only fetches
# what changed), the zip and build record to ~/xc/dist, the log to
# ~/xc/log-<version>-<mode>.txt.
set -euo pipefail

version="$1"
mode="$2"
jobs="${3:-4}"
tool="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/xc

resolved="$(python3 "$tool/resolve.py" "$version")"
field() { python3 -c "import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])" "$resolved" "$1"; }
dart="$(field dart)"
echo "$resolved"

python3 "$tool/fetch.py" --dart "$dart" --work ~/xc/work
python3 "$tool/build.py" --sdk ~/xc/work/dart/sdk --mode "$mode" \
  --sdk-hash "$(field sdk_hash)" --dart-version "$(field dart_version)" \
  --out ~/xc/dist --jobs "$jobs"
