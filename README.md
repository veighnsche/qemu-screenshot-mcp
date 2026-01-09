# QEMU Screenshot MCP Server

A Model Context Protocol (MCP) server that provides tools for interacting with running QEMU instances. Currently, it allows an agent to capture a high-quality screenshot of the first running QEMU virtual machine.

## Features

- 🔍 **Auto-discovery**: Automatically finds the first running `qemu-system-*` process.
- 🔌 **QMP Integration**: Uses the QEMU Machine Protocol (QMP) for reliable, window-independent screenshot capture.
- 🖼️ **Auto-Conversion**: Automatically converts QEMU's raw PPM output to PNG via Pillow for immediate use in AI interfaces.
- 🚀 **Standardized Return**: Returns screenshots as base64-encoded PNG strings that agents can easily interpret.

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

## Usage

### Using with `uvx` (Recommended)

You can run the server directly without manual installation using `uvx`:

```bash
# Point --from to the directory where this project is located
uvx --from /path/to/qemu-screenshot-mcp qemu-screenshot
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
        "/home/vince/Projects/qemu-screenshot-mcp",
        "qemu-screenshot"
      ]
    }
  }
}
```

## Tools Provided

### `capture_screenshot`
Captures a screenshot of the first running QEMU instance.
- **Returns**: A base64-encoded PNG string encased in standard image markers.
- **Error Handling**: Provides detailed feedback if no QEMU process is found, if QMP is missing, or if the socket is unreachable.

## Development & Testing

A mock server is provided in `tests/mock_qmp_server.py` to test the MCP server without a real QEMU instance.

1. **Start Mock Server**: `python3 tests/mock_qmp_server.py`
2. **Mock QEMU Process**: Rename a long-running process to `qemu-system-mock` and run it with `-qmp unix:/tmp/qmp-test.sock`.
3. **Run MCP Client**: Test the tool via your preferred MCP client or `uv run qemu-screenshot`.

## License
MIT
