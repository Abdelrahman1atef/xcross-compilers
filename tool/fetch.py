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

    def write_gclient(skip_perfetto, mirrors=None):
        # perfetto (tracing) is fetched from a Fuchsia mirror that no longer
        # exists for some revisions. Dart's build files need it where it can be
        # fetched, so it is skipped only after a first sync failed.
        deps = {'sdk/third_party/perfetto': None} if skip_perfetto else {}
        deps.update(mirrors or {})
        custom_deps = '{' + ', '.join(
            f'"{name}": ' + ('None' if url is None else f'"{url}"')
            for name, url in deps.items()) + '}'
        with open(os.path.join(dart, '.gclient'), 'w', encoding='utf-8') as gclient:
            gclient.write('\n'.join([
                'solutions = [{',
                '  "name": "sdk",',
                f'  "url": "{DART_SDK}",',
                '  "deps_file": "DEPS",',
                '  "managed": False,',
                f'  "custom_vars": {{{custom_vars}}},',
                f'  "custom_deps": {custom_deps},',
                '}]',
                '',
            ]))

    gclient = shutil.which('gclient.bat' if windows else 'gclient', path=env['PATH'])
    if gclient is None:
        raise SystemExit('gclient was not found in depot_tools')
    sync = [gclient, 'sync', '--no-history', '--shallow', '-D', '--force',
            '--reset', '--revision', f'sdk@{args.dart}', '--jobs', '8']
    write_gclient(skip_perfetto=False)
    if sync_ok(sync, dart, env):
        print(f'Dart SDK {args.dart} is in {os.path.join(dart, "sdk")}')
        return
    print('The sync failed; trying again without third_party/perfetto', flush=True)
    write_gclient(skip_perfetto=True)
    output = []
    if not sync_ok(sync, dart, env, output):
        # Some pinned commits are no longer served by dart.googlesource.com
        # (HTTP 400 on fetch-by-hash), while the GitHub mirror still has them.
        mirrors = github_mirrors(''.join(output), dart)
        if not mirrors:
            raise SystemExit('gclient sync failed')
        for name, url in mirrors.items():
            print(f'{name}: fetching from {url}', flush=True)
        write_gclient(skip_perfetto=True, mirrors=mirrors)
        run(sync, cwd=dart, env=env)
    print(f'Dart SDK {args.dart} is in {os.path.join(dart, "sdk")}')


def sync_ok(sync, cwd, env, output=None):
    """Runs gclient sync, echoing its output (and keeping it in output)."""
    print('+ ' + ' '.join(sync), flush=True)
    process = subprocess.Popen(sync, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace')
    for line in process.stdout:
        sys.stdout.write(line)
        if output is not None:
            output.append(line)
    sys.stdout.flush()
    return process.wait() == 0


def github_mirrors(log, dart):
    """dep -> GitHub mirror URL@revision for deps whose fetch failed.

    gclient reports a failed dep as "Command '... origin <hash>' returned
    non-zero exit status ... in <checkout>/<dep>". Only dart.googlesource.com
    repositories are mapped (to github.com/dart-lang/<repo>).
    """
    mirrors = {}
    pattern = re.compile(
        r"origin ([0-9a-f]{40})' returned non-zero exit status \d+ in (\S+)")
    for revision, path in pattern.findall(log):
        name = os.path.relpath(path, dart).replace(os.sep, '/')
        if name.startswith('..') or name == 'sdk/third_party/perfetto':
            continue
        remote = subprocess.run(['git', '-C', path, 'remote', 'get-url', 'origin'],
                                capture_output=True, text=True, check=False).stdout.strip()
        match = re.fullmatch(r'https://dart\.googlesource\.com/(?:external/github\.com/dart-lang/)?'
                             r'([\w.-]+?)(?:\.git)?/?', remote)
        repo = match.group(1) if match else (None if remote else os.path.basename(path))
        if repo:
            mirrors[name] = f'https://github.com/dart-lang/{repo}.git@{revision}'
    return mirrors


if __name__ == '__main__':
    sys.exit(main())
