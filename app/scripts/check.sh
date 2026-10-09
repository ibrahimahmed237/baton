#!/usr/bin/env bash
# Builds and tests the Baton app with the toolchain that works on this Mac.
#
# Usage: app/scripts/check.sh [extra arguments for `swift test`]
# Set SDKROOT yourself to skip the search below and use exactly that SDK.
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sdk_dir="/Library/Developer/CommandLineTools/SDKs"
plugin_dir="/Library/Developer/CommandLineTools/usr/lib/swift/host/plugins/testing"
cd "$app_dir"

# The managed command environment cannot write the user's default module cache.
# Keep check caches inside the package, respecting explicit caller overrides.
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-$app_dir/.build/check-cache/clang}"
export SWIFT_MODULECACHE_PATH="${SWIFT_MODULECACHE_PATH:-$app_dir/.build/check-cache/swift}"
mkdir -p "$CLANG_MODULE_CACHE_PATH" "$SWIFT_MODULECACHE_PATH"

probe_dir="$(mktemp -d)"
trap 'rm -rf "$probe_dir"' EXIT
cat > "$probe_dir/probe.swift" <<'SWIFT'
import SwiftUI
struct Probe: View { @State private var count = 0; var body: some View { Text("\(count)") } }
SWIFT

# A SwiftUI file with @State is what fails when the SDK and the toolchain's macro
# plugins do not match, so it stands in for a full build as a quick test.
works_with() { # $1 = SDK path, or empty for the toolchain's own default
    if [ -n "$1" ]; then
        swiftc -typecheck -parse-as-library -sdk "$1" "$probe_dir/probe.swift" >"$probe_dir/probe.log" 2>&1
    else
        swiftc -typecheck -parse-as-library "$probe_dir/probe.swift" >"$probe_dir/probe.log" 2>&1
    fi
}

test_flags=()
if [ -d "$plugin_dir" ]; then
    test_flags=(-Xswiftc -plugin-path -Xswiftc "$plugin_dir")
fi
if [ -n "${SDKROOT:-}" ]; then
    echo "check.sh: using SDKROOT from the environment: $SDKROOT"
elif works_with ""; then
    echo "check.sh: plain toolchain works"
else
    chosen=""
    # Newest first; the unversioned MacOSX.sdk is a link to one of the others.
    for sdk in $(ls -1 "$sdk_dir" 2>/dev/null | grep -E '^MacOSX[0-9.]+\.sdk$' | sort -V -r); do
        if works_with "$sdk_dir/$sdk"; then chosen="$sdk_dir/$sdk"; break; fi
    done
    if [ -z "$chosen" ]; then
        echo "check.sh: no SDK under $sdk_dir can compile SwiftUI with this toolchain" >&2
        head -12 "$probe_dir/probe.log" >&2
        exit 1
    fi
    echo "check.sh: plain toolchain fails; falling back to $chosen"
    export SDKROOT="$chosen"
fi

echo "check.sh: swift build"
swift build --disable-sandbox
echo "check.sh: swift test"
swift test --disable-sandbox ${test_flags[@]+"${test_flags[@]}"} "$@"
