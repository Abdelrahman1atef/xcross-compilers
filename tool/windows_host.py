#!/usr/bin/env python3
"""Lets Dart's Windows build tooling work with the build machine's Visual Studio
and Windows SDK.

    python3 tool/windows_host.py <dart checkout>/sdk/build/vs_toolchain.py

Only the build machine's setup changes, never the compiler: when GN is
generated, Dart's vs_toolchain.py copies the ARM64 C++ runtime DLLs from
VC/Redist/MSVC/<x.y.z>/arm64/Microsoft.VC143.CRT, the 2022 folder name.
Visual Studio 2026 names it Microsoft.VC145.CRT, so the copy failed with
"The system cannot find the path specified". This makes it fall back to the
Microsoft.VC14*.CRT folder that exists.

Newer Dart (3.12+, Flutter 3.50) asks vcvarsall for Windows SDK
10.0.28000.0 in build/toolchain/win/setup_toolchain.py; a machine without
it fails at `gn gen` (its "um" include folder does not exist). That SDK only
builds the compiler program for Windows; the iOS code it writes does not
depend on it (verify.py compares it with Flutter's byte for byte). When the
wanted SDK is missing, the newest installed one is used.

Running it twice changes nothing.
"""

import os
import re
import sys

MARKER = '# xcross-compilers: newer VC CRT folder'


def edit(text):
    if MARKER in text:
        return text, False
    anchor = re.compile(
        r"^(?P<indent>[ \t]+)source_dir = os\.path\.join\(vc_redist_root,\s*\n"
        r"\s*'arm64', vc_toolset_dir\)\n",
        re.MULTILINE,
    )
    match = anchor.search(text)
    if match is None:
        raise SystemExit("build/vs_toolchain.py: the arm64 CRT folder line was not found")
    indent = match.group('indent')
    fallback = (
        f'{indent}{MARKER}\n'
        f'{indent}if not os.path.isdir(source_dir):\n'
        f"{indent}  found = sorted(glob.glob(os.path.join(\n"
        f"{indent}      vc_redist_root, 'arm64', 'Microsoft.VC14*.CRT')))\n"
        f'{indent}  if found:\n'
        f'{indent}    source_dir = found[-1]\n'
    )
    return text[:match.end()] + fallback + text[match.end():], True


SDK_MARKER = '# xcross-compilers: installed Windows SDK'

# Inserted after `SDK_VERSION = '...'` in setup_toolchain.py.
SDK_FALLBACK = '''# xcross-compilers: installed Windows SDK
def _xcross_installed_sdk(wanted):
  import os as _os
  root = _os.path.join(_os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                       'Windows Kits', '10', 'Include')
  if _os.path.isdir(_os.path.join(root, wanted, 'um')) or not _os.path.isdir(root):
    return wanted
  found = [d for d in _os.listdir(root)
           if d.startswith('10.') and _os.path.isdir(_os.path.join(root, d, 'um'))]
  found.sort(key=lambda v: [int(x) for x in v.split('.') if x.isdigit()])
  return found[-1] if found else wanted
SDK_VERSION = _xcross_installed_sdk(SDK_VERSION)
'''


def edit_sdk(text):
    if SDK_MARKER in text:
        return text, False
    match = re.search(r"^SDK_VERSION = '[0-9.]+'\n", text, re.MULTILINE)
    if match is None:
        return text, False  # older Dart: vcvarsall picks the SDK itself
    return text[:match.end()] + SDK_FALLBACK + text[match.end():], True


def patch(path, editor, message):
    with open(path, encoding='utf-8', newline='') as source:
        text = source.read()
    crlf = '\r\n' in text
    edited, changed = editor(text.replace('\r\n', '\n'))
    if not changed:
        print(f'{path}: unchanged')
        return
    if crlf:
        edited = edited.replace('\n', '\r\n')
    with open(path, 'w', encoding='utf-8', newline='') as target:
        target.write(edited)
    print(f'{path}: {message}')


CONFIG_MARKER = '# xcross-compilers: allow clang older than the STL expects'


def edit_config(text):
    """build/config/win/BUILD.gn: Visual Studio 2026's C++ library stops clang
    older than 22 (STL1000); Dart before 3.11 bundles an older clang. The macro
    only turns that version check off."""
    if CONFIG_MARKER in text:
        return text, False
    anchor = '    "_SECURE_ATL",' + chr(10)
    if anchor not in text:
        return text, False
    insert = ''.join([
        anchor,
        chr(10),
        '    ', CONFIG_MARKER, chr(10),
        '    "_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH",', chr(10),
    ])
    return text.replace(anchor, insert, 1), True


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: windows_host.py <dart checkout>/sdk/build/vs_toolchain.py')
    path = sys.argv[1]
    patch(path, edit, 'arm64 CRT folder falls back to the Microsoft.VC14*.CRT that exists')
    setup = os.path.join(os.path.dirname(path), 'toolchain', 'win', 'setup_toolchain.py')
    if os.path.isfile(setup):
        patch(setup, edit_sdk, 'falls back to the newest installed Windows SDK')
    config = os.path.join(os.path.dirname(path), 'config', 'win', 'BUILD.gn')
    if os.path.isfile(config):
        patch(config, edit_config, 'defines _ALLOW_COMPILER_AND_STL_VERSION_MISMATCH')


if __name__ == '__main__':
    main()
