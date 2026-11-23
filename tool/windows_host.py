#!/usr/bin/env python3
"""Lets Dart's Windows build tooling work with a Visual Studio newer than 2022.

    python3 tool/windows_host.py <dart checkout>/sdk/build/vs_toolchain.py

Only the build machine's setup changes, never the compiler: when GN is
generated, Dart's vs_toolchain.py copies the ARM64 C++ runtime DLLs from
VC/Redist/MSVC/<x.y.z>/arm64/Microsoft.VC143.CRT, the 2022 folder name.
Visual Studio 2026 names it Microsoft.VC145.CRT, so the copy failed with
"The system cannot find the path specified". This makes it fall back to the
Microsoft.VC14*.CRT folder that exists. Running it twice changes nothing.
"""

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


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: windows_host.py <dart checkout>/sdk/build/vs_toolchain.py')
    path = sys.argv[1]
    with open(path, encoding='utf-8', newline='') as source:
        text = source.read()
    crlf = '\r\n' in text
    edited, changed = edit(text.replace('\r\n', '\n'))
    if not changed:
        print(f'{path}: already set up')
        return
    if crlf:
        edited = edited.replace('\n', '\r\n')
    with open(path, 'w', encoding='utf-8', newline='') as target:
        target.write(edited)
    print(f'{path}: arm64 CRT folder falls back to the Microsoft.VC14*.CRT that exists')


if __name__ == '__main__':
    main()
