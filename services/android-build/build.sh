#!/usr/bin/env bash
# Build the Lyrebird Android app or the DJI MSDK V5 sample inside the android-build container.
set -euo pipefail
target="${1:-lyrebird}"
variant="${BUILD_VARIANT:-Debug}"   # Debug | Release (Release needs your own signing config)
mkdir -p /out
stamp="$(date +%Y%m%d-%H%M)"

require_key() {
  if [[ -z "${AIRCRAFT_API_KEY:-}" || "${AIRCRAFT_API_KEY}" == "Your_DJI_App_Key" ]]; then
    echo "AIRCRAFT_API_KEY is not set: add your DJI app key to .env (developer.dji.com -> Apps)." >&2
    echo "The key is bound to the package name (com.lyrebird.rc for Lyrebird)." >&2
    exit 1
  fi
}

msdk_versions() {
  local lb dji
  lb="$(grep -oP 'djiSdkVersion\s*=\s*"\K[^"]+' /workspace/lyrebird/LyrebirdApp/android-sdk-v5-as/dependencies.gradle || true)"
  dji="$(grep -oP 'Latest Version V\K[0-9.]+' /workspace/msdk-v5/README.md 2>/dev/null | head -1 || true)"
  echo "DJI MSDK used by Lyrebird: ${lb:-?}   latest in upstream/Mobile-SDK-Android-V5: ${dji:-not checked out}"
}

case "$target" in
  lyrebird|lyrebird-test)
    cd /workspace/lyrebird/LyrebirdApp/android-sdk-v5-as
    msdk_versions
    [[ "$target" == lyrebird ]] && require_key
    # local.properties is git-ignored upstream; AIRCRAFT_API_KEY is read from the environment.
    printf 'sdk.dir=%s\nMAPLIBRE_TOKEN=%s\n' "$ANDROID_HOME" "${MAPLIBRE_TOKEN:-dummy}" > local.properties
    if [[ "$target" == lyrebird-test ]]; then
      AIRCRAFT_API_KEY="${AIRCRAFT_API_KEY:-ci-placeholder}" ./gradlew --no-daemon \
        :lyrebird-core:testDebugUnitTest :app:testCurrentV5DebugUnitTest
      exit 0
    fi
    ./gradlew --no-daemon ":app:assembleCurrentV5${variant}"
    find ../lyrebird-app/build/outputs/apk -name '*.apk' -newer local.properties -print0 |
      while IFS= read -r -d '' apk; do cp -v "$apk" "/out/lyrebird-${stamp}-$(basename "$apk")"; done
    ;;
  msdk-sample)
    require_key
    cd /workspace/msdk-v5/SampleCode-V5/android-sdk-v5-as
    msdk_versions
    printf 'sdk.dir=%s\n' "$ANDROID_HOME" > local.properties
    ./gradlew --no-daemon -PAIRCRAFT_API_KEY="$AIRCRAFT_API_KEY" ":sample:assemble${variant}"
    find .. -path '*/build/outputs/apk/*' -name '*.apk' -newer local.properties -print0 |
      while IFS= read -r -d '' apk; do cp -v "$apk" "/out/msdk-v5-sample-${stamp}-$(basename "$apk")"; done
    ;;
  versions) msdk_versions ;;
  *) echo "usage: android-build [lyrebird|lyrebird-test|msdk-sample|versions]" >&2; exit 2 ;;
esac
echo "APKs are in data/apk/ -- install with: adb install -r data/apk/<file>.apk"
