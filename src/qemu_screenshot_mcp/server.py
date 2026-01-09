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

# Initialize FastMCP server
mcp = FastMCP("QEMU Screenshot")

def find_qemu_process():
    """Find the first running qemu-system-* process."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info.get('name') or ""
            if name.startswith('qemu-system-'):
                return proc
            cmdline = proc.info.get('cmdline') or []
            if any('qemu-system-' in arg for arg in cmdline):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

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

async def qmp_command(socket_path, command, args=None):
    """Execute a QMP command."""
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except Exception as e:
        return {"error": {"desc": f"Failed to connect to QMP socket: {str(e)}"}}
    
    try:
        await reader.readline()
        writer.write(json.dumps({"execute": "qmp_capabilities"}).encode() + b'\n')
        await writer.drain()
        await reader.readline()
        
        cmd = {"execute": command}
        if args:
            cmd["arguments"] = args
        
        writer.write(json.dumps(cmd).encode() + b'\n')
        await writer.drain()
        
        response = await reader.readline()
        return json.loads(response)
    finally:
        writer.close()
        await writer.wait_closed()

@mcp.tool()
async def capture_screenshot() -> str:
    """
    Captures a screenshot of the first running QEMU instance.
    Saves the image to a 'screenshots' directory and returns the file path and base64 data.
    """
    proc = find_qemu_process()
    if not proc:
        return "Error: No running QEMU instance found."
    
    socket_path = get_qmp_socket_path(proc)
    if not socket_path:
        return f"Error: QEMU process (PID {proc.pid}) found, but no QMP socket detected."

    if not os.path.exists(socket_path):
        return f"Error: QMP socket path '{socket_path}' does not exist."

    # Prepare storage directory
    cwd = Path.cwd()
    screenshot_dir = cwd / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"qemu_screenshot_{timestamp}.png"
    filepath = screenshot_dir / filename

    # QEMU's screendump command creates a PPM file.
    with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp_ppm:
        tmp_ppm_path = tmp_ppm.name

    try:
        res = await qmp_command(socket_path, "screendump", {"filename": tmp_ppm_path})
        
        if "error" in res:
            return f"Error from QMP: {res['error']['desc']}"

        if not os.path.exists(tmp_ppm_path) or os.path.getsize(tmp_ppm_path) == 0:
            return "Error: Screendump failed to produce a file."

        with Image.open(tmp_ppm_path) as img:
            img.save(filepath, format='PNG')
            
            # Also get base64 for direct display if needed
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            png_data = img_byte_arr.getvalue()
            
        encoded = base64.b64encode(png_data).decode('utf-8')
        
        return (
            f"Screenshot captured successfully!\n"
            f"Filename: {filename}\n"
            f"Path: {filepath.absolute()}\n"
            f"\n[image/png;base64,{encoded}]"
        )
    
    except Exception as e:
        return f"Error during screenshot capture: {str(e)}"
    finally:
        if os.path.exists(tmp_ppm_path):
            os.remove(tmp_ppm_path)

def main():
    mcp.run()

if __name__ == "__main__":
    main()
