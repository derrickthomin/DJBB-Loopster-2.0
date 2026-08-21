#include "fw_version.h"
#include "fw_build_date.h"
// Single definition point so PING and TEST_STATE agree. The date is a generated literal
// (fw_build_date.h, written by version_stamp.py), NOT __DATE__: SCons rebuilds on content
// change only, so __DATE__ silently froze on incremental builds (stuck at "Jul 21 2026").
const char *FW_BUILD_DATE = FW_BUILD_DATE_LIT;
