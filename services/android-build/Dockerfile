# One-shot Android build container for the Lyrebird app (DJI Mobile SDK V5) and, optionally,
# DJI's own MSDK V5 sample app (upstream/Mobile-SDK-Android-V5). Nothing here is distributed:
# the DJI SDK is fetched by Gradle from DJI's Maven repository under DJI's EULA, and you need
# your own DJI developer app key (AIRCRAFT_API_KEY, https://developer.dji.com/user/apps).
#
#   docker compose run --rm android-build lyrebird            # -> data/apk/lyrebird-*.apk
#   docker compose run --rm android-build msdk-sample         # -> data/apk/msdk-v5-sample-*.apk
#   docker compose run --rm android-build lyrebird-test       # unit tests, as in Lyrebird CI
ARG JDK_IMAGE=eclipse-temurin:21-jdk-noble
FROM ${JDK_IMAGE}

ARG CMDLINE_TOOLS_VERSION=13114758
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    GRADLE_USER_HOME=/root/.gradle
ENV PATH=${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends unzip curl git python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p ${ANDROID_HOME}/cmdline-tools \
    && curl -sSfL -o /tmp/tools.zip \
         "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" \
    && unzip -q /tmp/tools.zip -d ${ANDROID_HOME}/cmdline-tools \
    && mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
    && rm /tmp/tools.zip \
    && yes | sdkmanager --licenses >/dev/null \
    && sdkmanager --install "platform-tools" "platforms;android-36" >/dev/null
# Further SDK parts (build-tools, NDK) are installed by the Android Gradle plugin on demand;
# the licenses accepted above allow that.

COPY build.sh /usr/local/bin/gs-android-build
RUN chmod 0755 /usr/local/bin/gs-android-build
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/gs-android-build"]
CMD ["lyrebird"]
