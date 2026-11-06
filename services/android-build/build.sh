#!/usr/bin/env bash
# Build the Lyrebird Android app or the DJI MSDK V5 sample inside the android-build container.
#
# MSDK_VERSION=<x.y.z> builds Lyrebird against another DJI MSDK V5 version without touching the
# submodule: LyrebirdApp is copied to a working directory and djiSdkVersion is replaced there.
# The submodule pins the version only in android-sdk-v5-as/dependencies.gradle.
set -euo pipefail
target="${1:-lyrebird}"
variant="${BUILD_VARIANT:-Debug}"   # Debug | Release (Release needs your own signing config)
mkdir -p /out
stamp="$(date +%Y%m%d-%H%M)"
lb_src=/workspace/lyrebird/LyrebirdApp
lb_root="$lb_src"

require_key() {
  if [[ -z "${AIRCRAFT_API_KEY:-}" || "${AIRCRAFT_API_KEY}" == "Your_DJI_App_Key" ]]; then
    echo "AIRCRAFT_API_KEY is not set: add your DJI app key to .env (developer.dji.com -> Apps)." >&2
    echo "The key is bound to the package name (com.lyrebird.rc for Lyrebird)." >&2
    exit 1
  fi
}

lb_msdk_version() {
  grep -oP 'djiSdkVersion\s*=\s*"\K[^"]+' "$1/android-sdk-v5-as/dependencies.gradle" || true
}

msdk_versions() {
  local pinned dji
  pinned="$(lb_msdk_version "$lb_src")"
  dji="$(grep -oP 'Latest Version V\K[0-9.]+' /workspace/msdk-v5/README.md 2>/dev/null | head -1 || true)"
  echo "DJI MSDK pinned by Lyrebird: ${pinned:-?}   used for this build: $(lb_msdk_version "$lb_root")" \
       "  latest in upstream/Mobile-SDK-Android-V5: ${dji:-not checked out}"
}

# With MSDK_VERSION set: copy LyrebirdApp to a working directory and switch the DJI SDK there.
prepare_lyrebird() {
  [[ -n "${MSDK_VERSION:-}" ]] || return 0
  if [[ ! "$MSDK_VERSION" =~ ^[0-9]+(\.[0-9]+){1,3}$ ]]; then
    echo "MSDK_VERSION must look like 5.20.1, got '$MSDK_VERSION'" >&2
    exit 2
  fi
  local work="${MSDK_WORKDIR:-/tmp/lyrebird-msdk}/msdk-${MSDK_VERSION}"
  rm -rf "$work" && mkdir -p "$work"
  cp -a "$lb_src" "$work/"
  lb_root="$work/LyrebirdApp"
  rm -rf "$lb_root"/*/build "$lb_root"/*/.gradle "$lb_root"/android-sdk-v5-as/local.properties
  sed -i -E "s/^([[:space:]]*djiSdkVersion[[:space:]]*=[[:space:]]*\")[^\"]+\"/\1${MSDK_VERSION}\"/" \
    "$lb_root/android-sdk-v5-as/dependencies.gradle"
  if [[ "$(lb_msdk_version "$lb_root")" != "$MSDK_VERSION" ]]; then
    echo "could not set djiSdkVersion=$MSDK_VERSION in the working copy" >&2
    exit 1
  fi
  echo "Working copy: $lb_root (submodule unchanged)"
}

case "$target" in
  lyrebird|lyrebird-test|lyrebird-check)
    prepare_lyrebird
    cd "$lb_root/android-sdk-v5-as"
    msdk_versions
    [[ "$target" == lyrebird ]] && require_key
    # local.properties is git-ignored upstream; AIRCRAFT_API_KEY is read from the environment.
    printf 'sdk.dir=%s\nMAPLIBRE_TOKEN=%s\n' "$ANDROID_HOME" "${MAPLIBRE_TOKEN:-dummy}" > local.properties
    tests=(:lyrebird-core:testDebugUnitTest :app:testCurrentV5DebugUnitTest)
    if [[ "$target" == lyrebird-test ]]; then
      AIRCRAFT_API_KEY="${AIRCRAFT_API_KEY:-ci-placeholder}" ./gradlew --no-daemon "${tests[@]}"
      exit 0
    fi
    if [[ "$target" == lyrebird-check ]]; then
      # Compile test: debug APK plus unit tests; --continue reports compile and test failures together.
      AIRCRAFT_API_KEY="${AIRCRAFT_API_KEY:-ci-placeholder}" ./gradlew --no-daemon --continue \
        :app:assembleCurrentV5Debug "${tests[@]}"
      echo "lyrebird-check: MSDK $(lb_msdk_version "$lb_root") builds, unit tests pass"
      exit 0
    fi
    ./gradlew --no-daemon ":app:assembleCurrentV5${variant}"
    suffix="${MSDK_VERSION:+msdk${MSDK_VERSION}-}"
    find ../lyrebird-app/build/outputs/apk -name '*.apk' -newer local.properties -print0 |
      while IFS= read -r -d '' apk; do cp -v "$apk" "/out/lyrebird-${stamp}-${suffix}$(basename "$apk")"; done
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
  *) echo "usage: [MSDK_VERSION=x.y.z] android-build [lyrebird|lyrebird-test|lyrebird-check|msdk-sample|versions]" >&2; exit 2 ;;
esac
echo "APKs are in data/apk/ -- install with: adb install -r data/apk/<file>.apk"
