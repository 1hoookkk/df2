import pathlib
import struct
import hashlib

p = pathlib.Path(r"c:\Users\hooki\df2-workstation\preset_library\talking_hedz.body240")
data = p.read_bytes()
sha = hashlib.sha256(data).hexdigest()
words = struct.unpack('<120H', data)

print(f"Talking Hedz Body: {p}")
print(f"SHA-256: {sha}")
print(f"Size: {len(data)} bytes\n")

corners = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
for ci, cname in enumerate(corners):
    print(f"Corner {ci} ({cname}):")
    s1_words = words[(ci * 6 + 0) * 5 : (ci * 6 + 1) * 5]
    s6_words = words[(ci * 6 + 5) * 5 : (ci * 6 + 6) * 5]
    s1_bytes = data[(ci * 6 + 0) * 10 : (ci * 6 + 1) * 10]
    s6_bytes = data[(ci * 6 + 5) * 10 : (ci * 6 + 6) * 10]
    print(f"  S1 Words: {[f'0x{w:04x}' for w in s1_words]}")
    print(f"  S1 Bytes (hex): {s1_bytes.hex()}")
    print(f"  S6 Words: {[f'0x{w:04x}' for w in s6_words]}")
    print(f"  S6 Bytes (hex): {s6_bytes.hex()}")
