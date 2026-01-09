import asyncio
import os
import json
import tempfile

SOCKET_PATH = "/tmp/qmp-test.sock"

async def handle_client(reader, writer):
    # 1. Send greeting
    greeting = {"QMP": {"version": {"qemu": {"micro": 0, "minor": 0, "major": 9}, "package": ""}, "capabilities": []}}
    writer.write(json.dumps(greeting).encode() + b'\n')
    await writer.drain()

    while True:
        data = await reader.readline()
        if not data:
            break
        
        req = json.loads(data.decode())
        execute = req.get("execute")
        
        if execute == "qmp_capabilities":
            writer.write(json.dumps({"return": {}}).encode() + b'\n')
        elif execute == "screendump":
            filename = req.get("arguments", {}).get("filename")
            # Create a fake PPM file
            # PPM P6 format header: P6 width height maxval
            with open(filename, "wb") as f:
                f.write(b"P6\n10 10\n255\n" + b"\xff\x00\x00" * 100) # 10x10 red image
            writer.write(json.dumps({"return": {}}).encode() + b'\n')
        else:
            writer.write(json.dumps({"error": {"desc": "Unknown command"}}).encode() + b'\n')
        
        await writer.drain()

    writer.close()
    await writer.wait_closed()

async def main():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    
    server = await asyncio.start_unix_server(handle_client, SOCKET_PATH)
    print(f"Mock QMP server listening on {SOCKET_PATH}")
    print(f"To test, run QEMU with: -name qemu-system-test -qmp unix:{SOCKET_PATH},server,nowait")
    print("Actually, just running a process with 'qemu-system-' in name is enough for the discovery logic.")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
