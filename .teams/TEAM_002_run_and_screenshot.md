# TEAM_002: Run and Screenshot Tool Implementation

## Objective
Implement `run_and_screenshot` - an atomic tool that starts QEMU, waits for boot, captures a screenshot, and shuts down in one deterministic step.

## Changes Made
- Added `run_and_screenshot` tool to `server.py`
  - Arguments: `arch`, `image`, `screenshot_delay_seconds`, `extra_args`
  - Full QEMU lifecycle management
  - QMP-based screenshot capture
  - Graceful cleanup with fallback to force kill

## Handoff Checklist
- [x] Implementation complete
- [ ] README updated
- [ ] Tests added (optional)
- [ ] Pushed to git
