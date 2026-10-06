"""Hash manifests, reparse-point refusal and crash-safe JSON. Nothing here deletes user data."""
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path


class SafetyError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def manifest(root):
    """Sorted [{path,bytes,sha256}] with POSIX-style relative paths; reparse points refused."""
    root = Path(root)
    if not root.is_dir():
        raise SafetyError(f"Missing directory: {root}")
    if _is_reparse(root):
        raise SafetyError("Save root must not be a reparse point")
    rows = []
    for current, directories, files in os.walk(root):
        for name in directories + files:
            if _is_reparse(os.path.join(current, name)):
                raise SafetyError("Save trees must not contain reparse points")
        for name in files:
            path = Path(current) / name
            rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                         "sha256": sha256_file(path)})
    return sorted(rows, key=lambda row: row["path"])


def verify(root, expected):
    actual = manifest(root)
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise SafetyError(f"File/hash mismatch: {root}")
    return len(actual)


def copy_tree(source, destination):
    """Copy a directory to a path that must not exist, then prove the copy is byte-identical."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise SafetyError(f"Refuse to overwrite: {destination}")
    expected = manifest(source)
    shutil.copytree(source, destination)
    verify(destination, expected)
    return expected


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
