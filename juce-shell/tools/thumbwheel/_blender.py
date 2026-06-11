#!/usr/bin/env python3
"""Talk to the live Blender MCP addon over its socket (port 9876).

Usage:
  python _blender.py scene                 # get_scene_info
  python _blender.py obj <NAME>            # get_object_info
  python _blender.py code <file.py>        # execute_code from a file
  python _blender.py code -                # execute_code from stdin
"""
import json, socket, sys

HOST, PORT = "localhost", 9876


def send(cmd):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(600)
    s.connect((HOST, PORT))
    s.sendall(json.dumps(cmd).encode())
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        try:
            json.loads(buf.decode())
            break
        except json.JSONDecodeError:
            continue
    s.close()
    return buf.decode()


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    if a[0] == "scene":
        cmd = {"type": "get_scene_info", "params": {}}
    elif a[0] == "obj":
        cmd = {"type": "get_object_info", "params": {"name": a[1]}}
    elif a[0] == "code":
        code = sys.stdin.read() if a[1] == "-" else open(a[1], encoding="utf-8").read()
        cmd = {"type": "execute_code", "params": {"code": code}}
    else:
        print("unknown:", a[0]); return
    print(send(cmd))


if __name__ == "__main__":
    main()
