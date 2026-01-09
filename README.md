# QEMU Screenshot MCP Server

A Model Context Protocol (MCP) server that provides tools for interacting with running QEMU instances. Currently, it allows an agent to capture a high-quality screenshot of the first running QEMU virtual machine.

## Features

- 🔍 **Auto-discovery**: Automatically finds the first running `qemu-system-*` process.
- 🔌 **QMP Integration**: Uses the QEMU Machine Protocol (QMP) for reliable, window-independent screenshot capture.
- 📁 **Persistent Storage**: Saves screenshots to a `screenshots/` directory with timestamped filenames for easy access.
- 🖼️ **Auto-Conversion**: Automatically converts QEMU's raw PPM output to PNG via Pillow for immediate use in AI interfaces.
- 🚀 **Detailed Response**: Returns the absolute file path and filename along with the base64-encoded PNG.

## Installation

This server is designed to be used with `uv` for seamless execution.

### Prerequisites

- Python 3.12+
- `uv` installed (`pip install uv`)
- A QEMU instance running with a Unix QMP socket.

### QEMU Configuration

To use this server, your QEMU instance **must** expose a Unix QMP socket. Run QEMU with the following argument:

```bash
qemu-system-x86_64 ... -qmp unix:/tmp/qmp-socket,server,nowait
```

```bash
# To run from your local directory:
uvx --from /home/vince/Projects/qemu-screenshot-mcp qemu-screenshot

# To run from a GitHub repository (after you push it):
uvx --from git+https://github.com/veighnsche/qemu-screenshot-mcp.git qemu-screenshot
```

### Configuration in Claude Desktop (or other MCP clients)
Add the following to your MCP configuration file (e.g., `config.json` for Claude Desktop):

```json
{
  "mcpServers": {
    "qemu-screenshot": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/veighnsche/qemu-screenshot-mcp.git",
        "qemu-screenshot"
      ]
    }
  }
}
```

> [!TIP]
> Once you push your project to GitHub, you can replace the local path in `--from` with the Git URL to make it accessible from anywhere!

## Tools Provided

### `run_and_screenshot`
**Atomic operation**: Starts a QEMU VM, waits for boot, captures a screenshot, then shuts down cleanly.

This is the **recommended tool for AI agents** as it provides a single, deterministic step for capturing VM state.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `arch` | string | ✅ | Architecture: `"x86_64"` or `"aarch64"` |
| `image` | string | ✅ | Path to ISO or disk image to boot |
| `screenshot_delay_seconds` | int | ✅ | Seconds to wait before screenshot (boot time) |
| `extra_args` | string | ❌ | Additional QEMU arguments (e.g., `"-m 2G -smp 2"`) |

**Example:**
```json
{
  "arch": "x86_64",
  "image": "/path/to/archlinux.iso",
  "screenshot_delay_seconds": 10,
  "extra_args": "-m 4G -enable-kvm"
}
```

**Returns**: Screenshot image with metadata, or detailed error message.

---

### `capture_screenshot`
Captures a screenshot of an **already running** QEMU instance.
- **Returns**: A base64-encoded PNG string encased in standard image markers.
- **Error Handling**: Provides detailed feedback if no QEMU process is found, if QMP is missing, or if the socket is unreachable.

## Development & Testing

A mock server is provided in `tests/mock_qmp_server.py` to test the MCP server without a real QEMU instance.

1. **Start Mock Server**: `python3 tests/mock_qmp_server.py`
2. **Mock QEMU Process**: Rename a long-running process to `qemu-system-mock` and run it with `-qmp unix:/tmp/qmp-test.sock`.
3. **Run MCP Client**: Test the tool via your preferred MCP client or `uv run qemu-screenshot`.

## License
MIT
