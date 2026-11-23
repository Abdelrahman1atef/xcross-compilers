#!/usr/bin/env python3
"""Finds the gen_snapshot command a real `flutter build ios` ran.

    python3 tool/reference_command.py --log build.log --flutter <sdk> \\
        --app <app> --mode release --out ref/

Writes ref/command.json and copies the app.dill to ref/app.dill. In
command.json the input is "{dill}" and every output path is "{out}/<name>",
so the same command can run another compiler on the same input:

    {"compiler": ".../gen_snapshot_arm64",
     "args": ["--deterministic", "--snapshot_kind=app-aot-macho-dylib",
              "--macho={out}/App.framework/App", "--macho-object={out}/app.o",
              ..., "{dill}"],
     "outputs": ["App.framework/App", "app.o"],
     "source": "log"}

The command comes from the verbose log (flutter assemble logs it). When the
log does not show it, it is rebuilt from what flutter_tools passes for iOS
(base/build.dart), and "source" says "flutter_tools".
"""

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import sys

# Output flags and the file each writes, by flag.
OUTPUTS = {
    '--macho': 'App.framework/App',
    '--macho-object': 'app.o',
    '--assembly': 'snapshot_assembly.S',
    '--elf': 'app.so',
}


def from_log(log):
    command = None
    with open(log, encoding='utf-8', errors='replace') as source:
        for line in source:
            if 'gen_snapshot' in line and '--snapshot_kind=' in line:
                command = line
    if command is None:
        return None
    words = shlex.split(command.strip(), posix=True)
    start = next(i for i, w in enumerate(words) if 'gen_snapshot' in os.path.basename(w))
    return words[start], words[start + 1:]


def from_flutter_tools(flutter, app, mode):
    """The iOS command flutter_tools builds for the default app."""
    compiler = os.path.join(
        flutter, 'bin', 'cache', 'artifacts', 'engine', f'ios-{mode}', 'gen_snapshot_arm64')
    build = open(os.path.join(flutter, 'packages', 'flutter_tools', 'lib', 'src', 'base',
                              'build.dart'), encoding='utf-8').read()
    if 'app-aot-macho-dylib' in build:
        plist = open(os.path.join(app, 'ios', 'Flutter', 'AppFrameworkInfo.plist'),
                     encoding='utf-8').read()
        min_os = re.search(r'<key>MinimumOSVersion</key>\s*<string>([^<]+)</string>', plist)
        args = [
            '--deterministic',
            '--snapshot_kind=app-aot-macho-dylib',
            '--macho=PLACEHOLDER',
            '--macho-object=PLACEHOLDER',
            f'--macho-min-os-version={min_os.group(1) if min_os else "13.0"}',
            '--macho-rpath=@executable_path/Frameworks,@loader_path/Frameworks',
            '--macho-install-name=@rpath/App.framework/App',
        ]
    else:
        args = ['--deterministic', '--snapshot_kind=app-aot-assembly', '--assembly=PLACEHOLDER']
    return compiler, args + ['app.dill']


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--log', required=True)
    parser.add_argument('--flutter', required=True)
    parser.add_argument('--app', required=True)
    parser.add_argument('--mode', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    found = from_log(args.log)
    source = 'log'
    if found is None:
        found = from_flutter_tools(args.flutter, args.app, args.mode)
        source = 'flutter_tools'
    compiler, words = found

    dills = sorted(glob.glob(os.path.join(args.app, '.dart_tool', 'flutter_build', '*', 'app.dill')),
                   key=os.path.getmtime)
    logged_dill = next((w for w in words if w.endswith('.dill') and os.path.isfile(w)), None)
    dill = logged_dill or (dills[-1] if dills else None)
    if dill is None:
        raise SystemExit('No app.dill found in the app')
    shutil.copyfile(dill, os.path.join(args.out, 'app.dill'))

    template, outputs = [], []
    for word in words:
        if word.endswith('.dill'):
            template.append('{dill}')
            continue
        flag, _, _ = word.partition('=')
        if flag in OUTPUTS:
            template.append(f'{flag}={{out}}/{OUTPUTS[flag]}')
            outputs.append(OUTPUTS[flag])
            continue
        template.append(word)
    if '{dill}' not in template or not outputs:
        raise SystemExit(f'Unexpected gen_snapshot command: {compiler} {" ".join(words)}')

    command = {'compiler': compiler, 'args': template, 'outputs': outputs, 'source': source}
    with open(os.path.join(args.out, 'command.json'), 'w', encoding='utf-8') as out_file:
        json.dump(command, out_file, indent=2)
    print(json.dumps(command, indent=2))


if __name__ == '__main__':
    sys.exit(main())
