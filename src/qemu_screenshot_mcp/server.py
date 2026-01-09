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
        return [TextContent(type="text", text="""\
Error: No running QEMU instance found.

TIP FOR AI AGENTS:
- QEMU must be running with a display (e.g., `-display gtk` or `-display sdl`).
- Headless QEMU (`-display none` or `-nographic`) cannot be screenshotted via X11.
- For headless VMs, use QMP with `-qmp unix:/tmp/qmp.sock,server,nowait`.""")]
    
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

    # No QEMU window found and no QMP - provide guidance
    if not window_id and not socket_path:
        return [TextContent(type="text", text="""\
Error: QEMU process found but no window or QMP socket detected.

TIP FOR AI AGENTS:
- The QEMU instance appears to be running headless (`-display none` or `-nographic`).
- Screenshots require either:
  1. A visible window: Start QEMU with `-display gtk` or `-display sdl`.
  2. QMP socket: Start QEMU with `-qmp unix:/tmp/qmp.sock,server,nowait`.
- Headless QEMU without QMP cannot provide screenshots.""")]

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


@mcp.tool()
async def run_and_screenshot(
    arch: str,
    image: str,
    screenshot_delay_seconds: int,
    extra_args: str = ""
):
    """
    Starts a QEMU VM, waits for it to boot, captures a screenshot, then shuts down.
    This is an atomic, deterministic operation for AI agents.
    
    Args:
        arch: Architecture to use - either "x86_64" or "aarch64"
        image: Path to the disk image or ISO to boot
        screenshot_delay_seconds: Seconds to wait before taking screenshot (for boot time)
        extra_args: Additional QEMU arguments (e.g., "-m 2G -smp 2")
    
    Returns:
        Screenshot image data and metadata, or error message
    """
    # Validate architecture
    if arch not in ("x86_64", "aarch64"):
        return [TextContent(type="text", text=f"Error: Invalid architecture '{arch}'. Must be 'x86_64' or 'aarch64'.")]
    
    # Validate image path
    image_path = Path(image)
    if not image_path.exists():
        return [TextContent(type="text", text=f"Error: Image file not found: {image}")]
    
    # Validate delay
    if screenshot_delay_seconds < 1:
        return [TextContent(type="text", text="Error: screenshot_delay_seconds must be at least 1.")]
    if screenshot_delay_seconds > 300:
        return [TextContent(type="text", text="Error: screenshot_delay_seconds cannot exceed 300 (5 minutes).")]
    
    # Create temp directory for QMP socket
    with tempfile.TemporaryDirectory() as tmpdir:
        qmp_socket = Path(tmpdir) / "qmp.sock"
        
        # Build QEMU command
        qemu_binary = f"qemu-system-{arch}"
        
        # Base command with QMP socket for screenshot
        cmd = [
            qemu_binary,
            "-qmp", f"unix:{qmp_socket},server,nowait",
            "-display", "gtk",  # Need a display for screenshot
        ]
        
        # Add architecture-specific defaults
        if arch == "aarch64":
            cmd.extend(["-machine", "virt", "-cpu", "cortex-a72"])
        else:
            cmd.extend(["-machine", "q35", "-cpu", "qemu64"])
        
        # Determine how to attach the image (ISO vs disk)
        image_str = str(image_path.absolute())
        if image_str.endswith(".iso"):
            cmd.extend(["-cdrom", image_str, "-boot", "d"])
        else:
            cmd.extend(["-drive", f"file={image_str},format=qcow2,if=virtio"])
        
        # Add extra args if provided
        if extra_args.strip():
            import shlex
            cmd.extend(shlex.split(extra_args))
        
        # TEAM_002: Start QEMU process
        qemu_proc = None
        try:
            qemu_proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for QMP socket to become available (with timeout)
            socket_ready = False
            for _ in range(50):  # 5 seconds max wait for socket
                await asyncio.sleep(0.1)
                if qmp_socket.exists():
                    socket_ready = True
                    break
                # Check if process died early
                if qemu_proc.returncode is not None:
                    _, stderr = await qemu_proc.communicate()
                    return [TextContent(type="text", text=f"Error: QEMU exited immediately.\nCommand: {' '.join(cmd)}\nStderr: {stderr.decode()}")]
            
            if not socket_ready:
                return [TextContent(type="text", text=f"Error: QMP socket did not appear within 5 seconds.\nCommand: {' '.join(cmd)}")]
            
            # Wait for the specified boot time
            await asyncio.sleep(screenshot_delay_seconds)
            
            # Check if QEMU is still running
            if qemu_proc.returncode is not None:
                _, stderr = await qemu_proc.communicate()
                return [TextContent(type="text", text=f"Error: QEMU exited before screenshot could be taken.\nStderr: {stderr.decode()}")]
            
            # Prepare screenshot directory
            try:
                cwd = Path.cwd()
                screenshot_dir = cwd / "screenshots"
                screenshot_dir.mkdir(exist_ok=True)
            except Exception as e:
                return [TextContent(type="text", text=f"Error: Failed to create screenshots directory: {str(e)}")]
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"qemu_{arch}_{timestamp}.png"
            filepath = screenshot_dir / filename
            
            # Take screenshot via QMP
            with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp_ppm:
                tmp_ppm_path = tmp_ppm.name
            
            try:
                res = await qmp_command(str(qmp_socket), "screendump", {"filename": tmp_ppm_path})
                
                if "error" in res:
                    return [TextContent(type="text", text=f"Error: QMP screendump failed: {res['error'].get('desc', str(res['error']))}")]
                
                # Small delay to ensure file is written
                await asyncio.sleep(0.2)
                
                if not os.path.exists(tmp_ppm_path) or os.path.getsize(tmp_ppm_path) == 0:
                    return [TextContent(type="text", text="Error: Screenshot file was not created or is empty.")]
                
                # Convert PPM to PNG
                with Image.open(tmp_ppm_path) as img:
                    img.save(filepath, format='PNG')
                
                # Build success response
                message = (
                    f"Screenshot captured successfully!\n"
                    f"Architecture: {arch}\n"
                    f"Image: {image}\n"
                    f"Boot delay: {screenshot_delay_seconds}s\n"
                    f"Filename: {filename}\n"
                    f"Path: {filepath.absolute()}"
                )
                
                return _create_success_response(filename, filepath, message)
                
            finally:
                if os.path.exists(tmp_ppm_path):
                    os.remove(tmp_ppm_path)
        
        except FileNotFoundError:
            return [TextContent(type="text", text=f"Error: QEMU binary '{qemu_binary}' not found. Is QEMU installed?")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: Unexpected error: {str(e)}")]
        finally:
            # Always clean up QEMU process
            if qemu_proc and qemu_proc.returncode is None:
                try:
                    # Try graceful shutdown via QMP first
                    if qmp_socket.exists():
                        await qmp_command(str(qmp_socket), "quit")
                        # Give it a moment to shut down gracefully
                        try:
                            await asyncio.wait_for(qemu_proc.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            pass
                    
                    # Force kill if still running
                    if qemu_proc.returncode is None:
                        qemu_proc.terminate()
                        try:
                            await asyncio.wait_for(qemu_proc.wait(), timeout=2.0)
                        except asyncio.TimeoutError:
                            qemu_proc.kill()
                            await qemu_proc.wait()
                except Exception:
                    # Last resort
                    try:
                        qemu_proc.kill()
                    except Exception:
                        pass


def main():
    mcp.run()

if __name__ == "__main__":
    main()
