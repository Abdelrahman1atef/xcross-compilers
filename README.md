# xcross-compilers

iOS arm64 AOT compilers (`gen_snapshot`) for **Linux and Windows** hosts, for every Flutter release. [xcross](https://github.com/Abdelrahman1atef/xcross-studio) uses them to build Flutter iOS release and profile apps without a Mac.

Flutter publishes the iOS `gen_snapshot` for macOS only. This repository builds the same compiler from the Dart SDK revision each Flutter release pins, for `linux-x64`, `linux-arm64`, `windows-x64` and `windows-arm64`, and only publishes a compiler after CI has shown that it writes **byte-identical** output to Flutter's official macOS compiler.

## Releases

Each release is named after a Flutter version (`3.47.8`) and has:

- `gen_snapshot-<release|profile>-<host>.zip`: the compiler at the root, plus `licenses/`.
- `manifest.json`: the Flutter version, engine and Dart revisions, and the SHA-256 of every zip and every executable. xcross checks both before it runs a compiler.

## How a release is made

All in GitHub Actions ([`build.yml`](.github/workflows/build.yml)):

1. **resolve**: the Flutter tag gives the engine revision and the Dart revision (`DEPS` `dart_revision`).
2. **reference** (macOS): installs that Flutter, runs `flutter build ios` on the `flutter create` app, and records the `app.dill`, the exact `gen_snapshot` arguments flutter_tools used, and the SHA-256 of what Flutter's official compiler writes.
3. **build** (each host): fetches the Dart SDK at that revision with the Dart team's own tools (depot_tools), turns on iOS as the compiler's target ([`tool/ios_target.py`](tool/ios_target.py)), and builds `gen_snapshot` with the GN settings Flutter uses for its iOS VM.
4. **verify** (each host): the built compiler compiles the same `app.dill` with the same arguments; its output must equal the official one byte for byte.
5. **publish**: only when all eight compilers passed.

[`watch.yml`](.github/workflows/watch.yml) runs every day and starts a build for every Flutter stable release that has no release here yet, so a new Flutter version is covered within hours.

Start one by hand:

```sh
gh workflow run build.yml -f flutter=3.47.8
```

Or build one on a Linux machine (or WSL), the way CI does:

```sh
tool/local_build.sh 3.47.8 release
```

## What changes in the Dart SDK

One GN argument, `xcross_ios_compiler`, added by [`tool/ios_target.py`](tool/ios_target.py):

- the compiler gets `DART_TARGET_OS_MACOS` and `DART_TARGET_OS_MACOS_IOS`, the defines Dart gives it when GN targets iOS (which needs a Mac), so it writes iOS arm64 code while it is built and run as a Linux or Windows program;
- release builds keep the timeline, as Flutter's iOS VM does (Dart removes it from Linux product builds).

The GN settings follow Flutter's engine for iOS: `dart_target_arch = "arm64"`, no compressed pointers, `dart_runtime_mode` release or profile, and `dart_sdk_verification_hash` set to the first ten characters of the Dart revision, as Flutter sets it.

## Licence

The tools in this repository: BSD 3-Clause ([LICENSE](LICENSE)). The compilers are builds of the Dart SDK; each zip carries the Dart SDK licence and the licences of the third-party code built into it.
