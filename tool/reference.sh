#!/usr/bin/env bash
# Builds the reference on macOS: what Flutter's own iOS compiler produces.
#
#   tool/reference.sh <flutter version> <release|profile> <out folder>
#
# Installs that Flutter, builds the default `flutter create` app for iOS (no
# signing), and takes the app.dill and the exact gen_snapshot command from
# the verbose log (tool/reference_command.py). It then reruns Flutter's
# official compiler on that app.dill and records the SHA-256 of every file
# it writes (App and app.o for Mach-O builds). tool/verify.py requires a
# built compiler to write the same bytes.
set -euo pipefail

version="$1"
mode="$2"
out="$(mkdir -p "$3" && cd "$3" && pwd)"
tool="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"

git clone --depth 1 --branch "$version" https://github.com/flutter/flutter.git "$work/flutter"
# Some releases (3.29.0) compute the engine version with
# `git merge-base HEAD origin/master` and, off the stable branch, overwrite the
# committed engine.version with it. A shallow tag clone has neither: name the
# checkout "stable" (keeps engine.version) and give it an origin/master.
# Later releases skip this when engine.version is tracked (ls-files).
script="$work/flutter/bin/internal/update_engine_version.sh"
if grep -q 'origin/master' "$script" 2>/dev/null && ! grep -q 'ls-files bin/internal/engine.version' "$script"; then
  git -C "$work/flutter" checkout -q -B stable
  git -C "$work/flutter" update-ref refs/remotes/origin/master HEAD
fi
export PATH="$work/flutter/bin:$PATH"
flutter --version
flutter precache --ios

cd "$work"
flutter create --platforms ios ref_app
cd ref_app
if ! flutter build ios "--$mode" --no-codesign -v > "$out/build.log" 2>&1; then
  tail -80 "$out/build.log"
  echo "flutter build ios --$mode failed" >&2
  exit 1
fi
echo "gen_snapshot lines in the build log:"
grep -n "gen_snapshot" "$out/build.log" | head -5 || true

python3 "$tool/reference_command.py" \
  --log "$out/build.log" --flutter "$work/flutter" --app "$work/ref_app" \
  --mode "$mode" --out "$out"

# Flutter's official compiler on the same input: the expected bytes.
python3 "$tool/run_compiler.py" --command "$out/command.json" \
  --compiler "$(python3 -c "import json;print(json.load(open('$out/command.json'))['compiler'])")" \
  --dill "$out/app.dill" --out "$out/official" --record "$out/official.json"
"$(python3 -c "import json;print(json.load(open('$out/command.json'))['compiler'])")" --version \
  > "$out/official-version.txt" 2>&1 || true
cat "$out/official.json"
