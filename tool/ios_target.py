#!/usr/bin/env python3
"""Lets a Linux or Windows build of the Dart SDK make an iOS compiler.

    python3 tool/ios_target.py <dart checkout>/sdk/runtime/BUILD.gn

Dart decides what its AOT compiler targets from GN's target_os: only
target_os == "ios" defines DART_TARGET_OS_MACOS and DART_TARGET_OS_MACOS_IOS,
and that needs a Mac with Xcode. This adds one GN argument,
xcross_ios_compiler, that gives a Linux or Windows build the same two
defines, so gen_snapshot emits iOS arm64 code (Mach-O assembly, the iOS
ABI) while it is still built and run as a host program.

It also keeps the timeline in release builds: Dart compiles it out of Linux
product VMs (DART_DISABLE_TIMELINE), and in the compiler that would fold
Timeline calls away, while Flutter's iOS VM keeps them.

The edit is anchored on the text it changes and stops with an error when an
anchor is missing, so a Dart version with a different layout is noticed
instead of silently built wrong. Running it twice changes nothing.
"""

import re
import sys

ARG = 'xcross_ios_compiler'
MARKER = f'# xcross-compilers: {ARG}'

DECLARE = f'''
{MARKER}
declare_args() {{
  # Build the AOT compiler for iOS arm64 on a Linux or Windows host.
  {ARG} = false
}}
'''

IOS_DEFINES = (
    f'  if ({ARG}) {{\n'
    '    defines += [\n'
    '      "DART_TARGET_OS_MACOS",\n'
    '      "DART_TARGET_OS_MACOS_IOS",\n'
    '    ]\n'
    '  } else '
)


def edit(text):
    if MARKER in text:
        return text, []
    changes = []

    # 1. The argument, after the imports at the top.
    imports = list(re.finditer(r'^import\("[^"]+"\)\n', text, re.MULTILINE))
    if not imports:
        raise SystemExit('runtime/BUILD.gn: no import() lines to place the argument after')
    end = imports[-1].end()
    text = text[:end] + DECLARE + text[end:]
    changes.append('declared xcross_ios_compiler')

    # 2. dart_os_config: the iOS defines first.
    os_config = re.search(r'config\("dart_os_config"\)\s*\{', text)
    if os_config is None:
        raise SystemExit('runtime/BUILD.gn: config("dart_os_config") not found')
    first_if = re.compile(r'^  if \(target_os == ', re.MULTILINE)
    branch = first_if.search(text, os_config.end())
    if branch is None:
        raise SystemExit('runtime/BUILD.gn: dart_os_config has no target_os branch')
    text = text[:branch.start()] + IOS_DEFINES + text[branch.start() + 2:]
    changes.append('dart_os_config: iOS defines when xcross_ios_compiler')

    # 3. Keep the timeline: every DART_DISABLE_TIMELINE that depends on a
    # Linux target also requires !xcross_ios_compiler.
    disable = re.compile(
        r'(if \([^)]*target_os == "linux")(\)\s*\{\s*defines \+= \[ "DART_DISABLE_TIMELINE" \])'
    )
    text, count = disable.subn(rf'\1 && !{ARG}\2', text)
    if count == 0 and 'DART_DISABLE_TIMELINE' in text:
        raise SystemExit(
            'runtime/BUILD.gn: DART_DISABLE_TIMELINE is set in a way this tool '
            'does not know; check it by hand'
        )
    if count:
        changes.append(f'timeline kept in {count} product config(s)')
    return text, changes


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: ios_target.py <dart checkout>/sdk/runtime/BUILD.gn')
    path = sys.argv[1]
    with open(path, encoding='utf-8', newline='') as source:
        text = source.read()
    edited, changes = edit(text)
    if not changes:
        print(f'{path}: already set up')
        return
    with open(path, 'w', encoding='utf-8', newline='') as target:
        target.write(edited)
    for change in changes:
        print(f'{path}: {change}')


if __name__ == '__main__':
    main()
