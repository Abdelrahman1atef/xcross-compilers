#!/usr/bin/env python3
"""Lets a Linux or Windows build of the Dart SDK make an iOS compiler.

    python3 tool/ios_target.py <dart checkout>/sdk

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

import os
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


VERSION_MARKER = 'xcross-compilers: iOS compiler built off macOS'

VERSION_HOST = (
    '#if defined(DART_TARGET_OS_MACOS_IOS) && !defined(DART_HOST_OS_MACOS)\n'
    f'    // {VERSION_MARKER}. This text is the DWARF\n'
    '    // producer of every App and app.o, so it names the host that\n'
    '    // Flutter\'s official iOS compiler names on Apple silicon, and the\n'
    '    // output is byte-identical to that compiler\'s.\n'
    '    " on \\"macos_arm64\\"";\n'
    '#else\n'
)


def edit_version(text):
    """Version::str_ ends with ' on "<host os>_<arch>"', and DWARF's producer
    in every App is "Dart " + that text: Flutter's compiler on a Mac says
    "macos_arm64", a Linux build "linux_simarm64". Use Flutter's."""
    if VERSION_MARKER in text:
        return text, []
    start = text.find('const char* Version::str_ =')
    if start < 0:
        raise SystemExit('runtime/vm/version_in.cc: Version::str_ not found')
    on = text.find('" on \\""', start)
    end = text.find(';\n', on)
    if on < 0 or end < 0:
        raise SystemExit('runtime/vm/version_in.cc: the " on \\"<host>\\"" part was not found')
    line = text.rfind('\n', 0, on) + 1
    original = text[line:end + 2]
    return (text[:line] + VERSION_HOST + original + '#endif\n' + text[end + 2:],
            ['version text: on "macos_arm64" for an iOS compiler off macOS'])


SORT_MARKER = 'xcross-compilers: order ties as macOS'

SORT_CALL = re.compile(
    r'^(?P<indent>[ \t]*)qsort\(data_,\s*length_,\s*sizeof\(T\),\s*'
    r'reinterpret_cast<CompareFunction>\(compare\)\);\n',
    re.MULTILINE,
)


def edit_sort(text):
    """GrowableArray::Sort calls the C library's qsort, and the order of
    ties is up to the library: an iOS compiler built off macOS uses
    platform/xcross_apple_sort.h, macOS's qsort, instead."""
    if SORT_MARKER in text:
        return text, []
    includes = list(re.finditer(r'^#include "platform/[^"]+"\n', text, re.MULTILINE))
    call = SORT_CALL.search(text)
    if not includes or call is None:
        raise SystemExit('runtime/platform/growable_array.h: the qsort call in Sort was not found')
    indent = call.group('indent')
    replacement = (
        '#if defined(DART_TARGET_OS_MACOS) && !defined(DART_HOST_OS_MACOS)\n'
        f'{indent}// {SORT_MARKER}\'s qsort does (see\n'
        f'{indent}// platform/xcross_apple_sort.h), so this iOS compiler writes the same\n'
        f'{indent}// App as Flutter\'s compiler on macOS.\n'
        f'{indent}xcross::AppleQsort(data_, length_, sizeof(T),\n'
        f'{indent}                   reinterpret_cast<CompareFunction>(compare));\n'
        '#else\n'
        f'{call.group(0)}'
        '#endif\n'
    )
    text = text[:call.start()] + replacement + text[call.end():]
    end = includes[-1].end()
    text = (text[:end] + '#include "platform/xcross_apple_sort.h"  // xcross-compilers\n'
            + text[end:])
    return text, ['Sort: macOS\'s qsort for an iOS compiler off macOS']


def install_sort_header(sdk):
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xcross_apple_sort.h')
    target = os.path.join(sdk, 'runtime', 'platform', 'xcross_apple_sort.h')
    with open(source, encoding='utf-8') as header:
        text = header.read()
    existing = None
    if os.path.isfile(target):
        with open(target, encoding='utf-8') as current:
            existing = current.read()
    if existing != text:
        with open(target, 'w', encoding='utf-8', newline='\n') as out:
            out.write(text)
        print(f'{target}: macOS\'s qsort and heapsort (BSD, from Apple\'s Libc)')


def edit_file(path, editor):
    with open(path, encoding='utf-8', newline='') as source:
        text = source.read()
    # A Windows checkout has CRLF line ends: edit with \n, write them back.
    crlf = '\r\n' in text
    edited, changes = editor(text.replace('\r\n', '\n'))
    if not changes:
        print(f'{path}: already set up')
        return
    if crlf:
        edited = edited.replace('\n', '\r\n')
    with open(path, 'w', encoding='utf-8', newline='') as target:
        target.write(edited)
    for change in changes:
        print(f'{path}: {change}')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: ios_target.py <dart checkout>/sdk')
    sdk = sys.argv[1]
    edit_file(os.path.join(sdk, 'runtime', 'BUILD.gn'), edit)
    edit_file(os.path.join(sdk, 'runtime', 'vm', 'version_in.cc'), edit_version)
    install_sort_header(sdk)
    edit_file(os.path.join(sdk, 'runtime', 'platform', 'growable_array.h'), edit_sort)


if __name__ == '__main__':
    main()
