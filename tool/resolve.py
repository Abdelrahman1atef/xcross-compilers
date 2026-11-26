#!/usr/bin/env python3
"""Resolves a Flutter release to the inputs of its iOS AOT compiler.

    python3 tool/resolve.py 3.47.8            # JSON on stdout
    python3 tool/resolve.py 3.47.8 --github-output "$GITHUB_OUTPUT"

The iOS compiler (gen_snapshot) is built from the Dart SDK revision the Flutter
engine pins, so only that revision decides it. Flutter keeps the engine in its
own repository since 3.29 (bin/internal/engine.version plus a root DEPS); older
releases pin the Dart revision in flutter/engine's DEPS instead.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

RAW = 'https://raw.githubusercontent.com/{repo}/{ref}/{path}'
VERSION = re.compile(r'^\d+\.\d+\.\d+$')
DART_REVISION = re.compile(r"""['"]dart_revision['"]\s*:\s*['"]([0-9a-f]{40})['"]""")


def fetch(repo, ref, path):
    """The text of [path] in [repo] at [ref], or None when it does not exist."""
    url = RAW.format(repo=repo, ref=ref, path=path)
    request = urllib.request.Request(url, headers={'User-Agent': 'xcross-compilers'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def dart_version(dart):
    """The Dart SDK version (3.13.5) from tools/VERSION at [dart]."""
    text = fetch('dart-lang/sdk', dart, 'tools/VERSION')
    if text is None:
        raise SystemExit(f'dart-lang/sdk has no tools/VERSION at {dart}')
    fields = dict(re.findall(r'^([A-Z_]+) (\S+)$', text, re.MULTILINE))
    version = f"{fields['MAJOR']}.{fields['MINOR']}.{fields['PATCH']}"
    if fields.get('CHANNEL') not in (None, 'stable'):
        version += f"-{fields['PRERELEASE']}.{fields['PRERELEASE_PATCH']}.{fields['CHANNEL']}"
    return version


def ios_compressed_pointers(flutter, engine):
    """Whether Flutter's engine built its iOS Dart VM with compressed pointers.

    Flutter 3.0.0 to 3.0.3 (and the 3.1.0 beta) turned them on for iOS; from
    3.0.4 on, only Android has them. The compiler must match the VM. Decided
    from the condition guarding dart_use_compressed_pointers in tools/gn.
    """
    gn = (fetch('flutter/flutter', flutter, 'engine/src/flutter/tools/gn')
          or fetch('flutter/engine', engine, 'tools/gn'))
    if gn is None:
        raise SystemExit(f'No engine tools/gn found for Flutter {flutter} (engine {engine})')
    lines = gn.splitlines()
    for index, line in enumerate(lines):
        if "gn_args['dart_use_compressed_pointers'] = True" not in line:
            continue
        start = index - 1
        while start >= 0 and not lines[start].lstrip().startswith('if '):
            start -= 1
        condition = '\n'.join(lines[max(start, 0):index])
        if "'ios'" in condition or '"ios"' in condition:
            return True
    return False


def resolve(flutter):
    if not VERSION.match(flutter):
        raise SystemExit(f'"{flutter}" is not a Flutter release such as 3.47.8')
    engine = fetch('flutter/flutter', flutter, 'bin/internal/engine.version')
    if engine is None:
        raise SystemExit(f'Flutter {flutter} has no bin/internal/engine.version')
    engine = engine.strip()
    deps = fetch('flutter/flutter', flutter, 'DEPS')
    match = DART_REVISION.search(deps or '')
    if match is None:
        # Before the engine moved into flutter/flutter.
        match = DART_REVISION.search(fetch('flutter/engine', engine, 'DEPS') or '')
    if match is None:
        raise SystemExit(f'No dart_revision found for Flutter {flutter} (engine {engine})')
    dart = match.group(1)
    return {
        'flutter': flutter,
        'engine': engine,
        'dart': dart,
        'dart_version': dart_version(dart),
        # Flutter builds its Dart VM with the SDK hash set to the first ten
        # characters of the Dart revision; the compiler must use the same,
        # or it refuses the app.dill Flutter compiles.
        'sdk_hash': dart[:10],
        'compressed_pointers': 'true' if ios_compressed_pointers(flutter, engine) else 'false',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('flutter', help='Flutter release, such as 3.47.8')
    parser.add_argument('--github-output', help='append key=value lines to this file')
    args = parser.parse_args()
    result = resolve(args.flutter)
    print(json.dumps(result, indent=2))
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as out:
            for key, value in result.items():
                out.write(f'{key}={value}\n')


if __name__ == '__main__':
    sys.exit(main())
