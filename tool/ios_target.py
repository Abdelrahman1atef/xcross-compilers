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
import shutil
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
    # Every translation unit, not only those that see the iOS target defines:
    # Sort is an inline template, and the linker keeps one copy of each
    # instantiation, so a unit that still called qsort could replace the
    # macOS-ordered copy everywhere (Windows hosts kept such a copy).
    replacement = (
        '#if !defined(DART_HOST_OS_MACOS)\n'
        f'{indent}// {SORT_MARKER}\'s qsort does (see\n'
        f'{indent}// platform/xcross_apple_sort.h), so this iOS compiler writes the same\n'
        f'{indent}// App as Flutter\'s compiler on macOS. Every unit uses it, so the\n'
        f'{indent}// linker cannot pick a qsort copy of an instantiation.\n'
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


ORDER_MARKER = 'xcross-compilers: in order'

ORDER_WHY = (
    'C++ leaves the order of call arguments and of the operands of an\n'
    '// overloaded "+" open; clang evaluates them left to right on Linux and\n'
    '// macOS but right to left for the Microsoft ABI (Windows). Each builder\n'
    '// call takes deopt ids, and the deopt id of a Suspend is its yield index\n'
    '// in the App, so they are taken in the order Flutter\'s compiler on macOS\n'
    '// takes them.'
)


def edit_deopt_ids(text):
    """kernel_to_il.cc: `new SuspendInstr(..., GetNextDeoptId(),
    GetNextDeoptId())` takes the two ids in either order: take them first."""
    if ORDER_MARKER in text:
        return text, []
    pair = re.compile(
        r'^(?P<indent>[ \t]*)(?P<head>[^;{}]*?)GetNextDeoptId\(\),\s*GetNextDeoptId\(\)'
        r'(?P<tail>[^;{}]*;)\n', re.MULTILINE)
    match = pair.search(text)
    if match is None or 'SuspendInstr' not in match.group(0):
        if 'SuspendInstr' not in text:
            print('kernel_to_il.cc: this Dart has no SuspendInstr; nothing to order')
            return text, []
        raise SystemExit('runtime/vm/compiler/frontend/kernel_to_il.cc: the two deopt ids of '
                         'SuspendInstr were not found')
    indent = match.group('indent')
    replacement = (
        f'{indent}// {ORDER_MARKER}.\n'
        f'{indent}// {ORDER_WHY.replace(chr(10), chr(10) + indent)}\n'
        f'{indent}const intptr_t xcross_deopt_id = GetNextDeoptId();\n'
        f'{indent}const intptr_t xcross_resume_deopt_id = GetNextDeoptId();\n'
        f'{indent}{match.group("head")}xcross_deopt_id, xcross_resume_deopt_id'
        f'{match.group("tail")}\n'
    )
    return (text[:match.start()] + replacement + text[match.end():],
            ['SuspendInstr: deopt ids taken in order'])


def edit_body_order(text):
    """kernel_binary_flowgraph.cc: `body = ClearRawParameters(...) +
    InitSuspendableFunction(...) + BuildFunctionBody(...)` builds the three in
    either order: build them one after the other."""
    if ORDER_MARKER in text:
        return text, []
    chain = re.compile(
        r'^(?P<indent>[ \t]*)const Fragment body =\s*'
        r'(?P<first>ClearRawParameters\([^;]*?\))\s*\+\s*'
        r'(?P<second>InitSuspendableFunction\([^;]*?\))\s*\+\s*'
        r'(?P<third>BuildFunctionBody\([^;]*?\));\n', re.MULTILINE)
    match = chain.search(text)
    if match is None:
        if 'InitSuspendableFunction' not in text:
            print('kernel_binary_flowgraph.cc: this Dart has no InitSuspendableFunction; '
                  'nothing to order')
            return text, []
        raise SystemExit('runtime/vm/compiler/frontend/kernel_binary_flowgraph.cc: '
                         'ClearRawParameters + InitSuspendableFunction + BuildFunctionBody '
                         'was not found')
    indent = match.group('indent')
    replacement = (
        f'{indent}// {ORDER_MARKER}.\n'
        f'{indent}// {ORDER_WHY.replace(chr(10), chr(10) + indent)}\n'
        f'{indent}Fragment xcross_body = {match.group("first")};\n'
        f'{indent}xcross_body += {match.group("second")};\n'
        f'{indent}xcross_body += {match.group("third")};\n'
        f'{indent}const Fragment body = xcross_body;\n'
    )
    return (text[:match.start()] + replacement + text[match.end():],
            ['function body: prologue parts built in order'])


BASENAME_MARKER = 'xcross-compilers: basename on Windows'

BASENAME_WINDOWS = (
    '#if defined(DART_HOST_OS_FUCHSIA)\n'
    '  // Not handled for this operating system.\n'
    '  return nullptr;\n'
    '#elif defined(DART_HOST_OS_WINDOWS)\n'
    f'  // {BASENAME_MARKER}. gen_snapshot names the DWARF compilation\n'
    '  // unit of an App after its file (App.framework/App: "App"); without a\n'
    '  // basename it used the root library\'s URI, and the app.o differed from\n'
    '  // the one Flutter\'s compiler writes on macOS. POSIX basename, with\n'
    '  // both separators.\n'
    '  if (path == nullptr) return nullptr;\n'
    '  intptr_t end = static_cast<intptr_t>(strlen(path));\n'
    "  while (end > 1 && (path[end - 1] == '/' || path[end - 1] == '\\\\')) {\n"
    '    end--;\n'
    '  }\n'
    '  if (end == 0) return Utils::StrDup(".");\n'
    '  intptr_t start = end;\n'
    "  while (start > 0 && path[start - 1] != '/' && path[start - 1] != '\\\\') {\n"
    '    start--;\n'
    '  }\n'
    '  if (start == end) return Utils::StrNDup(path, 1);  // Only separators.\n'
    '  return Utils::StrNDup(path + start, end - start);\n'
    '#else\n'
)


def edit_basename(text):
    """platform/utils.cc: Utils::Basename returns null on Windows."""
    if BASENAME_MARKER in text:
        return text, []
    anchor = re.compile(
        r'#if defined\(DART_HOST_OS_FUCHSIA\) \|\| defined\(DART_HOST_OS_WINDOWS\)\n'
        r'\s*// Not handled for these operating systems\.\n'
        r'\s*return nullptr;\n'
        r'#else\n')
    start = text.find('char* Utils::Basename(const char* path) {')
    if start < 0:
        print('utils.cc: this Dart has no Utils::Basename (added in Dart 3.9); nothing to fix')
        return text, []
    match = anchor.search(text, start)
    if match is None:
        raise SystemExit('runtime/platform/utils.cc: the Windows branch of Utils::Basename '
                         'was not found')
    return (text[:match.start()] + BASENAME_WINDOWS + text[match.end():],
            ['Utils::Basename works on Windows'])


FFI_KIND_MARKER = 'xcross-compilers: callback_kind_ as on macOS'
FFI_KIND_WHY = (
    'xcross-compilers: callback_kind_ as on macOS. This Dart never sets it for\n'
    'non-callbacks (the @Native functions of dart:ui), so it keeps a byte of the\n'
    'null pointer the object was filled with, and the snapshot records it:\n'
    "128 under Flutter's macOS compiler, 255 on Linux. Only callbacks read it,\n"
    'and they set it.')


def edit_ffi_kind(text):
    """object.cc (Dart 3.1): FfiTrampolineData::New leaves callback_kind_ unset."""
    if FFI_KIND_MARKER in text:
        return text, []
    start = text.find('FfiTrampolineDataPtr FfiTrampolineData::New() {')
    if start < 0 or 'untag()->callback_kind_' not in text:
        print('object.cc: no FfiTrampolineData::callback_kind_ to set; nothing to fix')
        return text, []
    end = text.find('\n}\n', start)
    body = text[start:end]
    anchor = '  data->untag()->is_leaf_ = false;\n'
    if 'callback_kind_ =' in body:
        return text, []
    if anchor not in body:
        raise SystemExit('runtime/vm/object.cc: FfiTrampolineData::New has no is_leaf_ line')
    comment = ''.join(f'  // {line}\n' for line in FFI_KIND_WHY.split('\n'))
    body = body.replace(anchor, anchor + comment + '  data->untag()->callback_kind_ = 0x80;\n')
    return text[:start] + body + text[end:], ['FfiTrampolineData::callback_kind_ starts at 128']


ORIGINAL = '.xcross-orig'
HASH_MARKER = 'xcross-compilers: hash the unedited source'


def edit_snapshot_hash(text):
    """tools/make_version.py: hash a VM file's unedited copy when there is one.

    The snapshot hash Dart writes into every snapshot is an MD5 of some VM
    sources (VM_SNAPSHOT_FILES, object.cc among them). An edit to one of them
    would change that hash and so the output; Flutter's compiler hashed the
    unedited file.
    """
    if HASH_MARKER in text:
        return text, []
    match = re.search(r"\n( +)vmfilepath = os\.path\.join\(utils\.DART_DIR, 'runtime', 'vm', vmfilename\)\n",
                      text)
    if match is None:
        raise SystemExit('tools/make_version.py: the VM_SNAPSHOT_FILES loop was not found')
    indent = match.group(1)
    added = (f"{indent}if os.path.isfile(vmfilepath + '{ORIGINAL}'):  # {HASH_MARKER}\n"
             f"{indent}    vmfilepath += '{ORIGINAL}'\n")
    return text[:match.end()] + added + text[match.end():], ['snapshot hash from unedited VM files']


def edit_vm_file(sdk, name, editor):
    """Edits runtime/vm/<name>, first keeping an unedited copy for the snapshot hash."""
    path = os.path.join(sdk, 'runtime', 'vm', name)
    with open(path, encoding='utf-8', newline='') as source:
        text = source.read()
    if not editor(text.replace('\r\n', '\n'))[1]:
        print(f'{path}: already set up or nothing to change')
        return
    if not os.path.isfile(path + ORIGINAL):
        shutil.copyfile(path, path + ORIGINAL)
    edit_file(path, editor)
    edit_file(os.path.join(sdk, 'tools', 'make_version.py'), edit_snapshot_hash)


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
    frontend = os.path.join(sdk, 'runtime', 'vm', 'compiler', 'frontend')
    edit_file(os.path.join(frontend, 'kernel_to_il.cc'), edit_deopt_ids)
    edit_file(os.path.join(frontend, 'kernel_binary_flowgraph.cc'), edit_body_order)
    edit_file(os.path.join(sdk, 'runtime', 'platform', 'utils.cc'), edit_basename)
    edit_vm_file(sdk, 'object.cc', edit_ffi_kind)


if __name__ == '__main__':
    main()
