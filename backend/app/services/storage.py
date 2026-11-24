"""영구 볼륨 파일 저장 + APK 검증."""
import hashlib
import os
import struct
import uuid
import zipfile

from fastapi import HTTPException, UploadFile

from ..config import settings

SUBDIRS = ["apks", "icons", "screenshots", "reports", "backups", "quarantine", "evidence", "tmp"]


def root() -> str:
    return settings.STORAGE_DIR


def ensure_dirs() -> None:
    for sub in SUBDIRS:
        os.makedirs(os.path.join(root(), sub), exist_ok=True)


def abspath(rel: str) -> str:
    full = os.path.realpath(os.path.join(root(), rel))
    if not full.startswith(os.path.realpath(root()) + os.sep):
        raise HTTPException(400, "잘못된 파일 경로입니다.")
    return full


def new_rel(sub: str, ext: str) -> str:
    return f"{sub}/{uuid.uuid4().hex}{ext}"


async def save_upload(upload: UploadFile, sub: str, ext: str, max_bytes: int) -> tuple[str, int, str]:
    """스트리밍 저장. (상대경로, 크기, sha256) 반환. 크기 초과 시 413."""
    ensure_dirs()
    rel = new_rel(sub, ext)
    full = abspath(rel)
    digest, size = hashlib.sha256(), 0
    try:
        with open(full, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"파일 크기 제한({max_bytes // (1024 * 1024)}MB)을 초과했습니다.")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        if os.path.exists(full):
            os.remove(full)
        raise
    return rel, size, digest.hexdigest()


def save_bytes(data: bytes, sub: str, ext: str) -> tuple[str, int, str]:
    ensure_dirs()
    rel = new_rel(sub, ext)
    with open(abspath(rel), "wb") as out:
        out.write(data)
    return rel, len(data), hashlib.sha256(data).hexdigest()


def move_to_quarantine(rel: str) -> str:
    new = "quarantine/" + os.path.basename(rel)
    os.replace(abspath(rel), abspath(new))
    return new


def remove(rel: str) -> None:
    try:
        os.remove(abspath(rel))
    except (FileNotFoundError, HTTPException):
        pass


# ---------- APK 검사 ----------
def _axml_strings(data: bytes, off: int) -> list[str]:
    _, hsize, _, count, _, flags, strings_start, _ = struct.unpack_from("<HHIIIIII", data, off)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", data, off + hsize)
    base = off + strings_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            n = data[p]; p += 2 if n & 0x80 else 1
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]; p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]; p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]; p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def parse_manifest(data: bytes) -> dict:
    """바이너리 AndroidManifest.xml에서 package / versionCode / versionName 추출."""
    info: dict = {}
    if len(data) < 8 or struct.unpack_from("<H", data, 0)[0] != 0x0003:
        return info
    off, strings = 8, []
    while off + 8 <= len(data):
        ctype, hsize, csize = struct.unpack_from("<HHI", data, off)
        if csize <= 0:
            break
        if ctype == 0x0001:
            strings = _axml_strings(data, off)
        elif ctype == 0x0102:
            name_idx = struct.unpack_from("<I", data, off + 20)[0]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, off + 24)
            if 0 <= name_idx < len(strings) and strings[name_idx] == "manifest":
                base = off + 16 + attr_start
                for i in range(attr_count):
                    _, aname, raw, _, _, dtype, value = struct.unpack_from("<IIIHBBI", data, base + i * attr_size)
                    key = strings[aname] if aname < len(strings) else ""
                    if key == "package" and raw < len(strings):
                        info["package"] = strings[raw]
                    elif key == "versionCode":
                        info["version_code"] = value
                    elif key == "versionName":
                        idx = raw if raw != 0xFFFFFFFF else value
                        if dtype == 0x03 or raw != 0xFFFFFFFF:
                            info["version_name"] = strings[idx] if idx < len(strings) else ""
                return info
        off += csize
    return info


def inspect_apk(full_path: str) -> dict:
    """APK 구조 검증. {'ok': bool, 'reason': str, 'manifest': {...}}"""
    try:
        with open(full_path, "rb") as fh:
            if fh.read(4) != b"PK\x03\x04":
                return {"ok": False, "reason": "APK(ZIP) 형식이 아닙니다.", "manifest": {}}
        with zipfile.ZipFile(full_path) as zf:
            names = zf.namelist()
            if any(n.startswith("/") or ".." in n.split("/") for n in names):
                return {"ok": False, "reason": "경로 조작이 의심되는 항목이 포함되어 있습니다.", "manifest": {}}
            if "AndroidManifest.xml" not in names:
                return {"ok": False, "reason": "AndroidManifest.xml이 없습니다.", "manifest": {}}
            if not any(n.endswith(".dex") for n in names):
                return {"ok": False, "reason": "실행 코드(classes.dex)가 없습니다.", "manifest": {}}
            total = sum(i.file_size for i in zf.infolist())
            if total > 8 * 1024 ** 3:
                return {"ok": False, "reason": "압축 해제 크기가 비정상적으로 큽니다.", "manifest": {}}
            manifest = parse_manifest(zf.read("AndroidManifest.xml"))
    except (zipfile.BadZipFile, OSError, struct.error):
        return {"ok": False, "reason": "손상된 APK 파일입니다.", "manifest": {}}
    return {"ok": True, "reason": "", "manifest": manifest}
