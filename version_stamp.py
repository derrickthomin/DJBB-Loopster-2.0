# PlatformIO pre-build hook: keep the firmware build date fresh.
#
# fw_version.cpp stamps __DATE__ into FW_BUILD_DATE, which the web UI compares against the
# GitHub release date to decide "up to date / update available". __DATE__ only updates when
# that file is recompiled, so touch it every build -- a ~5-line translation unit, negligible
# to rebuild -- and the reported date is never stale, even on incremental dev builds.
#
# Inherited by env:loopster-release via `extends` (release overrides only build_flags), so
# customer builds get an accurate date too.
Import("env")
import os

src = os.path.join(env.subst("$PROJECT_SRC_DIR"), "fw_version.cpp")
if os.path.isfile(src):
    os.utime(src, None)
