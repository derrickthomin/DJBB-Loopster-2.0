#pragma once
// Firmware build date, stamped by the compiler (__DATE__ -> "Mmm dd yyyy", C locale, always
// English) in fw_version.cpp so every translation unit reports the same string. Sent in the
// PING ack and TEST_STATE as "built"; the web UI compares it to the GitHub release date to
// decide "up to date / update available" with zero manual version bookkeeping. A pre-build
// hook (version_stamp.py) re-touches fw_version.cpp each build so the date is never stale,
// even on incremental dev builds.
extern const char *FW_BUILD_DATE;
