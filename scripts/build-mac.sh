#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Prefer the full Xcode toolchain; honor an explicitly selected DEVELOPER_DIR.
if [[ -z "${DEVELOPER_DIR:-}" && -d /Applications/Xcode.app/Contents/Developer ]]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
export CLANG_MODULE_CACHE_PATH="$PROJECT_DIR/.build/clang-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$PROJECT_DIR/.build/module-cache"
mkdir -p "$PROJECT_DIR/.build"
xcrun swift build --product LunchMac --configuration release --disable-sandbox
BIN_DIR="$(xcrun swift build --configuration release --show-bin-path --disable-sandbox)"
APP_DIR="$PROJECT_DIR/dist/camp.app"
mkdir -p "$APP_DIR/Contents/MacOS"
cp "$BIN_DIR/LunchMac" "$APP_DIR/Contents/MacOS/LunchlineMac"
cp "$PROJECT_DIR/Config/Mac-Info.plist" "$APP_DIR/Contents/Info.plist"
codesign --force --sign - "$APP_DIR"
printf 'Built %s\n' "$APP_DIR"
if [[ "${1:-}" == "--open" ]]; then
    open "$APP_DIR"
fi
