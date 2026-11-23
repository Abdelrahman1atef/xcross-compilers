#!/usr/bin/env python3
"""Fetches the Dart SDK at one revision, with what building gen_snapshot needs.

    python3 tool/fetch.py --dart <40-char revision> --work work

Leaves <work>/depot_tools and <work>/dart/sdk. Uses the Dart team's own
tools (depot_tools gclient), so the compiler is built from exactly the
sources and the pinned clang, gn, ninja and sysroot the Dart revision names.
Optional downloads the compiler does not need (browsers, Android, Fuchsia,
remote build clients) are switched off.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys

DEPOT_TOOLS = 'https://chromium.googlesource.com/chromium/tools/depot_tools.git'
DART_SDK = 'https://dart.googlesource.com/sdk.git'

# Dart DEPS variables for downloads gen_snapshot never uses.
SKIP = {
    'download_reclient': False,
    'download_chrome': False,
    'download_firefox': False,
    'download_emscripten': False,
    'download_android_deps': False,
    'download_fuchsia_deps': False,
    'checkout_javascript_engines': False,
    'checkout_benchmarks_internal': False,
    'checkout_flute': False,
}


def run(command, cwd=None, env=None):
    print('+ ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dart', required=True, help='dart-lang/sdk revision')
    parser.add_argument('--work', required=True, help='working folder')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.dart):
        raise SystemExit('--dart must be a full 40-character revision')

    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    windows = platform.system() == 'Windows'

    depot = os.path.join(work, 'depot_tools')
    if not os.path.isdir(depot):
        run(['git', 'clone', '--depth', '1', DEPOT_TOOLS, depot])
    env = dict(os.environ)
    env['PATH'] = depot + os.pathsep + env['PATH']
    env['DEPOT_TOOLS_UPDATE'] = '0'
    env['DEPOT_TOOLS_METRICS'] = '0'
    if windows:
        # Use the Visual Studio on this machine, not Google's internal one.
        env['DEPOT_TOOLS_WIN_TOOLCHAIN'] = '0'
        run(['git', 'config', '--global', 'core.longpaths', 'true'])

    dart = os.path.join(work, 'dart')
    os.makedirs(dart, exist_ok=True)
    custom_vars = ', '.join(f'"{k}": {v}' for k, v in SKIP.items())
    with open(os.path.join(dart, '.gclient'), 'w', encoding='utf-8') as gclient:
        gclient.write(
            'solutions = [{\n'
            '  "name": "sdk",\n'
            f'  "url": "{DART_SDK}",\n'
            '  "deps_file": "DEPS",\n'
            '  "managed": False,\n'
            f'  "custom_vars": {{{custom_vars}}},\n'
            '}]\n'
        )
    gclient = shutil.which('gclient.bat' if windows else 'gclient', path=env['PATH'])
    if gclient is None:
        raise SystemExit('gclient was not found in depot_tools')
    run(
        [gclient, 'sync', '--no-history', '--shallow', '-D', '--force',
         '--reset', '--revision', f'sdk@{args.dart}', '--jobs', '8'],
        cwd=dart,
        env=env,
    )
    print(f'Dart SDK {args.dart} is in {os.path.join(dart, "sdk")}')


if __name__ == '__main__':
    sys.exit(main())
