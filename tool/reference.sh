#!/usr/bin/env bash
# Builds the reference on macOS: what Flutter's own iOS compiler produces.
#
#   tool/reference.sh <flutter version> <release|profile> <out folder>
#
# Installs that Flutter, builds the default `flutter create` app for iOS
# (no signing), takes the app.dill and the exact gen_snapshot arguments
# from the verbose log, and recompiles the app.dill with Flutter's official
# gen_snapshot to record the SHA-256 of its assembly. tool/verify.py then
# requires a built compiler to produce the same bytes.
set -euo pipefail

version="$1"
mode="$2"
out="$(mkdir -p "$3" && cd "$3" && pwd)"
work="$(mktemp -d)"

git clone --depth 1 --branch "$version" https://github.com/flutter/flutter.git "$work/flutter"
export PATH="$work/flutter/bin:$PATH"
flutter --version
flutter precache --ios

cd "$work"
flutter create --platforms ios ref_app
cd ref_app
flutter build ios "--$mode" --no-codesign -v 2>&1 | tee "$out/build.log" >/dev/null

# The gen_snapshot command flutter_tools ran (one line in the verbose log).
python3 - "$out/build.log" "$out" <<'PY'
import json, os, re, shlex, sys
log, out = sys.argv[1], sys.argv[2]
command = None
for line in open(log, encoding='utf-8', errors='replace'):
    if re.search(r'gen_snapshot\S* .*--snapshot_kind=app-aot-assembly', line):
        command = line
if command is None:
    raise SystemExit('No gen_snapshot command found in the build log')
command = command[command.index(next(t for t in command.split() if 'gen_snapshot' in t)):]
words = shlex.split(command.strip())
compiler, rest = words[0], words[1:]
dill = next(w for w in rest if w.endswith('.dill'))
flags = [w for w in rest if w != dill and not w.startswith('--assembly=')]
json.dump({'compiler': compiler, 'dill': dill, 'flags': flags}, open(os.path.join(out, 'command.json'), 'w'), indent=2)
json.dump(flags, open(os.path.join(out, 'flags.json'), 'w'), indent=2)
print('compiler:', compiler)
print('flags:', ' '.join(flags))
PY

compiler="$(python3 -c "import json,sys;print(json.load(open('$out/command.json'))['compiler'])")"
dill="$(python3 -c "import json,sys;print(json.load(open('$out/command.json'))['dill'])")"
cp "$dill" "$out/app.dill"
flags=()
while IFS= read -r flag; do flags+=("$flag"); done < <(python3 -c "import json;[print(f) for f in json.load(open('$out/flags.json'))]")
"$compiler" "${flags[@]}" "--assembly=$out/official.S" "$out/app.dill"
shasum -a 256 "$out/official.S" | cut -d' ' -f1 > "$out/official.sha256"
"$compiler" --version > "$out/official-version.txt" 2>&1 || true
echo "official $(cat "$out/official.sha256") for Flutter $version $mode"
