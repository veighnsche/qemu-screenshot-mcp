import asyncio
import os
import sys
from pathlib import Path

# Add the src directory to sys.path
sys.path.append(str(Path.cwd() / "src"))

from qemu_screenshot_mcp.server import capture_screenshot

async def main():
    print("Attempting to capture screenshot using updated logic...")
    results = await capture_screenshot()
    for res in results:
        if hasattr(res, 'text'):
            print(f"Text: {res.text}")
        if hasattr(res, 'data'):
            print(f"Image data received (base64 length: {len(res.data)})")
            # Save the received data to a file for verification
            with open("test_screenshot.png", "wb") as f:
                import base64
                f.write(base64.b64decode(res.data))
            print("Saved image data to test_screenshot.png")

if __name__ == "__main__":
    asyncio.run(main())
