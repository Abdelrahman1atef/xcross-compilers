#!/usr/bin/env python3
"""Builds the iOS arm64 gen_snapshot for this host from a Dart SDK checkout.

    python3 tool/build.py --sdk work/dart/sdk --mode release \\
        --sdk-hash 416e33b0ff --dart-version 3.13.7 --out dist

Writes dist/gen_snapshot-<mode>-<host>.zip (the executable at the root and
licenses/) and dist/build-<mode>-<host>.json. The GN arguments are the ones
Flutter's engine uses for its iOS Dart VM, so the compiler's output matches
what that VM loads:

- dart_target_arch arm64 (iOS devices), no compressed pointers (Flutter keeps
  them off on iOS);
- dart_runtime_mode release (product) or profile;
- dart_sdk_verification_hash set like Flutter's (first ten characters of the
  Dart revision), or the compiler refuses Flutter's app.dill;
- xcross_ios_compiler (tool/ios_target.py) for the iOS target defines.
"""

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import zipfile

TOOL = os.path.dirname(os.path.abspath(__file__))


def host():
    system = platform.system()
    os_name = {'Linux': 'linux', 'Windows': 'windows'}.get(system)
    if os_name is None:
        raise SystemExit(f'Unsupported host {system}: build on Linux or Windows')
    machine = platform.machine().lower()
    cpu = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    if cpu is None:
        raise SystemExit(f'Unsupported CPU {machine}')
    return os_name, cpu


def gn_args(mode, os_name, cpu, sdk_hash):
    args = {
        'target_os': 'win' if os_name == 'windows' else 'linux',
        'target_cpu': cpu,
        'host_cpu': cpu,
        'dart_target_arch': 'arm64',
        'dart_use_compressed_pointers': False,
        'dart_runtime_mode': 'release' if mode == 'release' else 'profile',
        'is_debug': False,
        'is_release': mode == 'profile',
        'is_product': mode == 'release',
        'dart_debug': False,
        'is_clang': True,
        'use_rbe': False,
        'dart_sdk_verification_hash': sdk_hash,
        'xcross_ios_compiler': True,
    }
    if os_name == 'linux':
        args['dart_sysroot'] = 'debian'
    return args


def visual_studio(env):
    """Points Dart's toolchain script at the installed Visual Studio.

    Dart's build/vs_toolchain.py only looks in the 2017, 2019 and 2022
    folders; a newer Visual Studio (the windows-11-arm runners have one) is
    not found unless vs2022_install names it.
    """
    if any(env.get(f'vs{year}_install') for year in ('2022', '2019', '2017')):
        return
    vswhere = os.path.join(
        env.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
        'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if not os.path.isfile(vswhere):
        return
    found = subprocess.run(
        [vswhere, '-latest', '-products', '*', '-format', 'json'],
        capture_output=True, text=True, check=False).stdout
    try:
        install = json.loads(found)[0]
    except (ValueError, IndexError):
        return
    path = install.get('installationPath')
    version = install.get('installationVersion', '')
    if path and not version.startswith(('15.', '16.', '17.')):
        env['vs2022_install'] = path
        print(f'Visual Studio {version} at {path}: used as vs2022_install', flush=True)


def gn_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return f'"{value}"'


def run(command, cwd, env=None, capture=False):
    print('+ ' + ' '.join(command), flush=True)
    return subprocess.run(
        command, cwd=cwd, env=env, check=True, text=capture,
        capture_output=capture,
    )


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sdk', required=True, help='<checkout>/sdk')
    parser.add_argument('--mode', choices=['release', 'profile'], required=True)
    parser.add_argument('--sdk-hash', required=True)
    parser.add_argument('--dart-version', required=True, help='expected --version')
    parser.add_argument('--out', required=True)
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    args = parser.parse_args()

    sdk = os.path.abspath(args.sdk)
    os_name, cpu = host()
    host_name = f'{os_name}-{cpu}'
    windows = os_name == 'windows'
    exe = '.exe' if windows else ''

    run([sys.executable, os.path.join(TOOL, 'ios_target.py'),
         os.path.join(sdk, 'runtime', 'BUILD.gn')], cwd=sdk)

    gn = os.path.join(sdk, 'buildtools', 'win', 'gn.exe') if windows else os.path.join(sdk, 'buildtools', 'gn')
    ninja = os.path.join(sdk, 'buildtools', 'ninja', 'ninja' + exe)
    for tool in (gn, ninja):
        if not os.path.isfile(tool):
            raise SystemExit(f'{tool} is missing: run tool/fetch.py first')

    out = os.path.join('out', f'xcross-ios-{args.mode}-{host_name}')
    arguments = gn_args(args.mode, os_name, cpu, args.sdk_hash)
    env = dict(os.environ)
    if windows:
        env['DEPOT_TOOLS_WIN_TOOLCHAIN'] = '0'
        visual_studio(env)
        run([sys.executable, os.path.join(TOOL, 'windows_host.py'),
             os.path.join(sdk, 'build', 'vs_toolchain.py')], cwd=sdk)
    run([gn, 'gen', out, '--args=' + ' '.join(f'{k}={gn_value(v)}' for k, v in arguments.items())],
        cwd=sdk, env=env)
    run([ninja, '-C', out, '-j', str(args.jobs), 'gen_snapshot'], cwd=sdk, env=env)

    built = os.path.join(sdk, out, 'gen_snapshot' + exe)
    stripped = os.path.join(sdk, out, 'exe.stripped', 'gen_snapshot' + exe)
    binary = stripped if os.path.isfile(stripped) else built
    if not os.path.isfile(binary):
        raise SystemExit(f'ninja did not produce {built}')

    # The compiler must name the Dart version Flutter's SDK reports.
    check = run([binary, '--version'], cwd=sdk, capture=True)
    said = (check.stdout + check.stderr).strip()
    print(said)
    if f'Dart SDK version: {args.dart_version} ' not in said + ' ':
        raise SystemExit(f'gen_snapshot --version says "{said}", expected Dart {args.dart_version}')

    os.makedirs(args.out, exist_ok=True)
    name = f'gen_snapshot-{args.mode}-{host_name}.zip'
    archive = os.path.join(args.out, name)
    licenses = {
        'LICENSE.dart': os.path.join(sdk, 'LICENSE'),
        'LICENSE.zlib': os.path.join(sdk, 'third_party', 'zlib', 'LICENSE'),
        'LICENSE.boringssl': os.path.join(sdk, 'third_party', 'boringssl', 'src', 'LICENSE'),
        'LICENSE.double-conversion': os.path.join(
            sdk, 'runtime', 'third_party', 'double-conversion', 'LICENSE'),
    }
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        entry = zipfile.ZipInfo('gen_snapshot' + exe, date_time=(1980, 1, 1, 0, 0, 0))
        entry.external_attr = (stat.S_IFREG | 0o755) << 16
        entry.create_system = 3
        entry.compress_type = zipfile.ZIP_DEFLATED
        with open(binary, 'rb') as source:
            zip_file.writestr(entry, source.read())
        for license_name, path in licenses.items():
            if os.path.isfile(path):
                zip_file.write(path, f'licenses/{license_name}')

    record = {
        'asset': name,
        'mode': args.mode,
        'host': host_name,
        'sha256': sha256(archive),
        'executable_sha256': sha256(binary),
        'size': os.path.getsize(archive),
        'version': said,
        'gn_args': arguments,
    }
    with open(os.path.join(args.out, f'build-{args.mode}-{host_name}.json'), 'w', encoding='utf-8') as out_file:
        json.dump(record, out_file, indent=2)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    sys.exit(main())
