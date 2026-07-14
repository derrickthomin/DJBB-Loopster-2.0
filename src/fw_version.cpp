#include "fw_version.h"
// Single definition point so PING and TEST_STATE agree. version_stamp.py touches this file
// before every build, forcing a recompile so __DATE__ reflects the actual build day.
const char *FW_BUILD_DATE = __DATE__;
