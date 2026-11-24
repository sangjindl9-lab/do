"""검증용 최소 APK 생성기(바이너리 AndroidManifest 포함). 테스트와 E2E 스크립트가 함께 쓴다."""
import io
import struct
import uuid
import zipfile


def make_apk(package: str, version_code: int = 1, version_name: str = "1.0", dex: bool = True, extra: dict | None = None) -> bytes:
    """검증용 최소 APK(바이너리 AndroidManifest 포함)."""
    strings = ["manifest", "package", "versionCode", "versionName", package, version_name]
    blob, offsets = b"", []
    for s in strings:
        offsets.append(len(blob))
        enc = s.encode("utf-16-le")
        blob += struct.pack("<H", len(s)) + enc + b"\x00\x00"
    blob += b"\x00" * (-len(blob) % 4)
    header = 28
    pool = struct.pack("<HHIIIIII", 0x0001, header, header + 4 * len(strings) + len(blob), len(strings), 0, 0,
                       header + 4 * len(strings), 0) + struct.pack(f"<{len(strings)}I", *offsets) + blob
    attrs = (struct.pack("<IIIHBBI", 0xFFFFFFFF, 1, 4, 8, 0, 0x03, 4) +
             struct.pack("<IIIHBBI", 0xFFFFFFFF, 2, 0xFFFFFFFF, 8, 0, 0x10, version_code) +
             struct.pack("<IIIHBBI", 0xFFFFFFFF, 3, 5, 8, 0, 0x03, 5))
    elem = struct.pack("<HHIIIIIHHHHHH", 0x0102, 16, 16 + 20 + len(attrs), 1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 20, 20, 3, 0, 0, 0) + attrs
    manifest = struct.pack("<HHI", 0x0003, 8, 8 + len(pool) + len(elem)) + pool + elem
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", manifest)
        if dex:
            zf.writestr("classes.dex", b"dex\n035\x00" + uuid.uuid4().bytes)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()
