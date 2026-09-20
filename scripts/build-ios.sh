#!/bin/bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
if [[ ! -x "$DEVELOPER_DIR/usr/bin/xcodebuild" ]]; then
  echo 'Install Xcode with an iOS 17+ SDK, or set DEVELOPER_DIR to your Xcode installation.' >&2
  exit 1
fi
xcode_major="$(xcodebuild -version | awk '/^Xcode / {split($2, v, "."); print v[1]}')"
if [[ "$xcode_major" -lt 15 ]]; then
  echo "camp requires Xcode 15 or newer for interactive Live Activities. Installed: Xcode $xcode_major." >&2
  echo 'Install a newer Xcode compatible with this Mac, including its iOS Simulator runtime.' >&2
  exit 1
fi
# Override to a specific simulator with IOS_DESTINATION='platform=iOS Simulator,id=...'.
xcodebuild -project "$project_root/Lunchline.xcodeproj" -scheme Lunchline \
  -configuration Debug -destination "${IOS_DESTINATION:-generic/platform=iOS Simulator}" \
  -derivedDataPath "$project_root/DerivedData/iOS" CODE_SIGNING_ALLOWED=NO build
echo "Built: $project_root/DerivedData/iOS/Build/Products/Debug-iphonesimulator/camp.app"
