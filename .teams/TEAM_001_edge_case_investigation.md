# TEAM_001: Proactive Edge Case Investigation - QEMU Screenshot MCP

## Bug Report / Objective

This is a **proactive** investigation to identify potential edge cases and bugs in the `qemu-screenshot-mcp` server before they manifest in production.

## Environment

- **Platform**: Linux (Fedora), KDE Plasma, Wayland with XWayland
- **Python**: 3.12+
- **Tools Available**: `xprop`, `spectacle`, `import` (ImageMagick)

---

## Phase 1 — Symptom Candidates (Edge Cases)

The following are hypothesized edge cases that could cause failures:

### 1.1 No QEMU Process Running
- **Symptom**: Tool returns error "No running QEMU instance found."
- **Status**: HANDLED (line 110-111)

### 1.2 Multiple QEMU Instances
- **Symptom**: May capture wrong window or fail to find the correct one.
- **Current Behavior**: Takes the first with QMP, otherwise first X11 window with "qemu" in WM_CLASS.
- **Risk**: Medium - could capture wrong VM.

### 1.3 Pure Wayland QEMU (no XWayland)
- **Symptom**: `xprop` fails, targeted capture fails, falls back to desktop capture.
- **Current Behavior**: Falls back to `spectacle` (full desktop).
- **Risk**: High - user gets desktop instead of VM.

### 1.4 Missing `xprop` Binary
- **Symptom**: `find_qemu_window_id()` silently fails.
- **Current Behavior**: Returns None, falls through to spectacle/import.
- **Risk**: Low - graceful fallback.

### 1.5 Missing `spectacle` and `import` Binaries
- **Symptom**: All fallback commands fail.
- **Current Behavior**: Returns error message.
- **Risk**: Low - user is informed.

### 1.6 QMP Socket Permission Denied
- **Symptom**: QMP connect fails with permission error.
- **Current Behavior**: Falls back to X11.
- **Risk**: Low - graceful fallback.

### 1.7 QMP Socket Exists But QEMU Not Responding
- **Symptom**: QMP hangs or returns error.
- **Current Behavior**: MAY HANG INDEFINITELY (no timeout).
- **Risk**: HIGH - blocks the MCP server.

### 1.8 Race Condition: QEMU Window Closed During Capture
- **Symptom**: `import` or screenshot fails mid-operation.
- **Current Behavior**: Exception caught, continues to next fallback.
- **Risk**: Low - graceful fallback.

### 1.9 Screenshots Directory Not Writable
- **Symptom**: Cannot create/write to `screenshots/` directory.
- **Current Behavior**: MAY CRASH with unhandled exception.
- **Risk**: MEDIUM - needs error handling.

### 1.10 Very Large Screenshot (High Resolution)
- **Symptom**: Memory issues or slow encoding.
- **Current Behavior**: No limits, full image is base64 encoded.
- **Risk**: Low - unlikely to cause issues unless extreme.

### 1.11 Temp File Cleanup on Error
- **Symptom**: PPM temp files may be left behind on certain failure paths.
- **Current Behavior**: Finally block should handle, but verify.
- **Risk**: Low.

### 1.12 Empty Screenshot File
- **Symptom**: `import` or `spectacle` creates 0-byte file.
- **Current Behavior**: HANDLED (line 171 checks size > 0).

---

## Phase 2 — Hypotheses to Test

Based on Phase 1, the following are prioritized for testing:

| # | Hypothesis | Confidence | Evidence Needed |
|---|------------|------------|-----------------|
| H1 | QMP can hang indefinitely (no timeout) | HIGH | Code review + test |
| H2 | Screenshots dir write failure is unhandled | MEDIUM | Code review |
| H3 | Multiple QEMU instances may capture wrong one | MEDIUM | Test with 2 QEMUs |
| H4 | Pure Wayland QEMU fallback is weak | MEDIUM | Test on native Wayland |
| H5 | `tmp_ppm_path` may be undefined in finally block | LOW | Code review |

---

## Phase 3 — Testing Hypotheses

### H1: QMP Timeout Issue (HIGH PRIORITY)

**Code Review (lines 77-101):**
- `asyncio.open_unix_connection()` has no timeout.
- `reader.readline()` has no timeout.
- If QEMU is frozen, this will block forever.

**Evidence**: CONFIRMED - no timeout on any async operation.

**Recommendation**: Add `asyncio.wait_for()` with reasonable timeout (e.g., 5 seconds).

### H2: Screenshots Dir Write Failure

**Code Review (lines 124-126):**
- `screenshot_dir.mkdir(exist_ok=True)` - could fail with PermissionError.
- No try/except around this.

**Evidence**: CONFIRMED - unhandled exception possible.

**Recommendation**: Wrap in try/except and return user-friendly error.

### H5: tmp_ppm_path Undefined in Finally

**Code Review (lines 133-146):**
```python
with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp_ppm:
    tmp_ppm_path = tmp_ppm.name

try:
    ...
finally:
    if os.path.exists(tmp_ppm_path):
        os.remove(tmp_ppm_path)
```

**Evidence**: SAFE - `tmp_ppm_path` is always defined before try block.

---

## Phase 4 — Root Cause Summary

### Confirmed Issues:

1. **H1**: No timeout on QMP operations - can block forever.
2. **H2**: No error handling for screenshots dir creation.

### Recommended Fixes:

1. Add `asyncio.wait_for()` with 5s timeout to QMP operations.
2. Wrap `mkdir` in try/except.

---

## Phase 5 — Decision

These are **small fixes** (< 5 Units of Work, < 50 lines). Proceeding with immediate fix.

---

## Handoff Checklist

- [x] Symptom candidates documented.
- [x] Hypotheses formed and prioritized.
- [x] Evidence gathered via code review.
- [x] Root causes confirmed.
- [x] Fixes implemented.
- [x] Tests pass.
