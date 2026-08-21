#pragma once
// Firmware build date ("Mmm dd yyyy", C locale, always English), generated into
// fw_build_date.h by the version_stamp.py pre-build hook and compiled in via
// fw_version.cpp so every translation unit reports the same string. Sent in the
// PING ack and TEST_STATE as "built"; the web UI compares it to the GitHub release
// date to decide "up to date / update available" with zero manual version
// bookkeeping. Generated as file CONTENT (not __DATE__ + touch) because SCons
// skips recompiles when content is unchanged — mtime alone never triggered a
// rebuild and the stamp froze for weeks.
extern const char *FW_BUILD_DATE;
