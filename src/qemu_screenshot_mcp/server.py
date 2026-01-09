import asyncio
import os
import psutil
import json
import base64
import tempfile
import io
import datetime
from pathlib import Path
from PIL import Image
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

# Initialize FastMCP server
mcp = FastMCP("QEMU Screenshot")

async def find_qemu_window_id():
    """Find the X window ID of the QEMU instance."""
    try:
        # 1. Get list of window IDs
        process = await asyncio.create_subprocess_exec(
            "xprop", "-root", "_NET_CLIENT_LIST",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        
        # Parse window IDs: _NET_CLIENT_LIST(WINDOW): window id # 0x..., 0x...
        line = stdout.decode().strip()
        if "#" not in line:
            return None
        
        ids = [id.strip() for id in line.split("#")[1].split(",")]
        
        # 2. Check each window for QEMU class
        for window_id in ids:
            p = await asyncio.create_subprocess_exec(
                "xprop", "-id", window_id, "WM_CLASS",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            out, _ = await p.communicate()
            if p.returncode == 0 and "qemu" in out.decode().lower():
                return window_id
                
    except Exception:
        pass
    return None

def find_qemu_processes():
    """Find all running qemu-system-* processes."""
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info.get('name') or ""
            cmdline = proc.info.get('cmdline') or []
            if name.startswith('qemu-system-') or any('qemu-system-' in arg for arg in cmdline):
                processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return processes

def get_qmp_socket_path(proc):
    """Extract QMP socket path from qemu process cmdline."""
    cmdline = proc.info.get('cmdline') or []
    for i, arg in enumerate(cmdline):
        if arg == '-qmp' and i + 1 < len(cmdline):
            val = cmdline[i + 1]
            if val.startswith('unix:'):
                return val[5:].split(',')[0]
        elif arg.startswith('-qmp=unix:'):
            return arg[len('-qmp=unix:'):].split(',')[0]
    return None

# TEAM_001 BREADCRUMB: CONFIRMED - QMP operations need timeout to prevent hanging
QMP_TIMEOUT_SECONDS = 5

async def qmp_command(socket_path, command, args=None):
    """Execute a QMP command with timeout protection."""
    try:
        # TEAM_001: Added timeout to prevent indefinite blocking
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path),
            timeout=QMP_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return {"error": {"desc": f"Connection to QMP socket timed out after {QMP_TIMEOUT_SECONDS}s"}}
    except Exception as e:
        return {"error": {"desc": f"Failed to connect to QMP socket: {str(e)}"}}
    
    try:
        # Wrap all readline operations in timeout
        await asyncio.wait_for(reader.readline(), timeout=QMP_TIMEOUT_SECONDS)
        writer.write(json.dumps({"execute": "qmp_capabilities"}).encode() + b'\n')
        await writer.drain()
        await asyncio.wait_for(reader.readline(), timeout=QMP_TIMEOUT_SECONDS)
        
        cmd = {"execute": command}
        if args:
            cmd["arguments"] = args
        
        writer.write(json.dumps(cmd).encode() + b'\n')
        await writer.drain()
        
        response = await asyncio.wait_for(reader.readline(), timeout=QMP_TIMEOUT_SECONDS)
        return json.loads(response)
    except asyncio.TimeoutError:
        return {"error": {"desc": f"QMP command timed out after {QMP_TIMEOUT_SECONDS}s"}}
    finally:
        writer.close()
        await writer.wait_closed()

@mcp.tool()
async def capture_screenshot():
    """
    Captures a screenshot of the first running QEMU instance.
    Prioritizes QMP (window-independent), falls back to X11 (if available).
    """
    processes = find_qemu_processes()
    if not processes:
        return [TextContent(type="text", text="Error: No running QEMU instance found.")]
    
    # Prioritize processes with QMP
    qmp_proc = None
    socket_path = None
    for proc in processes:
        path = get_qmp_socket_path(proc)
        if path and os.path.exists(path):
            qmp_proc = proc
            socket_path = path
            break
    
    # TEAM_001 BREADCRUMB: CONFIRMED - mkdir needs error handling
    # Prepare storage directory with error handling
    try:
        cwd = Path.cwd()
        screenshot_dir = cwd / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)
    except PermissionError:
        return [TextContent(type="text", text="Error: Cannot create screenshots directory (permission denied).")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: Failed to create screenshots directory: {str(e)}")]
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"qemu_screenshot_{timestamp}.png"
    filepath = screenshot_dir / filename

    if socket_path:
        # Strategy 1: QMP Screendump
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp_ppm:
            tmp_ppm_path = tmp_ppm.name

        try:
            res = await qmp_command(socket_path, "screendump", {"filename": tmp_ppm_path})
            if "error" not in res and os.path.exists(tmp_ppm_path) and os.path.getsize(tmp_ppm_path) > 0:
                with Image.open(tmp_ppm_path) as img:
                    img.save(filepath, format='PNG')
                return _create_success_response(filename, filepath)
        except Exception:
            pass # Fallback to X11 if QMP fails
        finally:
            if os.path.exists(tmp_ppm_path):
                os.remove(tmp_ppm_path)

    # Strategy 2: X11/XWayland Targeted Fallback
    # Try to find a specific QEMU window first.
    window_id = await find_qemu_window_id()
    
    fallback_commands = []
    if window_id:
        fallback_commands.append(["import", "-window", window_id, str(filepath)])
    
    # Generic fallbacks if targeted fails or window not found
    fallback_commands.extend([
        ["spectacle", "-b", "-n", "-o", str(filepath)],  # KDE/Wayland/X11
        ["import", "-window", "root", str(filepath)],    # ImageMagick/X11
    ])

    for cmd in fallback_commands:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                # Add a message about how we captured it
                method = "Targeted Window" if window_id and cmd[1] == "-window" and cmd[2] != "root" else "Desktop Capture"
                msg = f"Screenshot captured successfully using {method}!"
                return _create_success_response(filename, filepath, msg)
        except Exception:
            continue

    return [TextContent(type="text", text="Error: Failed to capture screenshot using any available method (QMP, Targeted X11, Spectacle all failed).")]

def _create_success_response(filename, filepath, message=None):
    with open(filepath, "rb") as f:
        png_data = f.read()
    encoded = base64.b64encode(png_data).decode('utf-8')
    
    if message is None:
        message = f"Screenshot captured successfully!\nFilename: {filename}\nPath: {filepath.absolute()}"
    else:
        message = f"{message}\nFilename: {filename}\nPath: {filepath.absolute()}"
    
    return [
        TextContent(
            type="text", 
            text=message
        ),
        ImageContent(
            type="image",
            data=encoded,
            mimeType="image/png"
        )
    ]

def main():
    mcp.run()

if __name__ == "__main__":
    main()
