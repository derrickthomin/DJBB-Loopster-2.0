#pragma once
// FIRMWARE VERSION — the single source of truth for "what release is this".
//
// ⚠ BUMP THIS WHEN CUTTING A RELEASE. It must equal the GitHub release tag without the
// leading "v" (tag v3.2 -> "3.2"). The web config's "Check for Updates" compares this string
// (sent in the PING ack as "version") against the latest release tag; a stale value here
// makes every customer on the new release see "update available" forever, or hides a real
// update. Release checklist: notes/CODEBASE_MAP.md "Cutting a release".
//
// Hand-maintained on purpose: the old compile-date scheme (__DATE__ / generated header +
// GitHub publish-time comparison with a 7-day slack) silently froze and was more machinery
// than a project this size needs. Dev builds between releases report the last release —
// they read "up to date", which is fine.
constexpr const char *FW_VERSION = "3.1";
