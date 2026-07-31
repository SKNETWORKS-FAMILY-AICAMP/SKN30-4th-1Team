"""파일 저장소 추상화 레이어.

로컬 파일시스템을 기본으로 사용하며, UPLOAD_DIR 환경변수로 루트 경로를 지정한다.
추후 S3 등 클라우드 스토리지로 교체할 때는 이 모듈만 수정하면 된다.
"""
import os
import stat
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "data/uploads"))


class UnsafeUploadPathError(ValueError):
    pass


def _absolute(path: str | os.PathLike) -> Path:
    """Normalize `.`/`..` without resolving symlinks."""
    return Path(os.path.abspath(os.fspath(path)))


def upload_root() -> Path:
    return _absolute(os.getenv("UPLOAD_DIR", str(_UPLOAD_DIR)))


def _safe_lstat(path: Path):
    try:
        return path.lstat()
    except OSError as exc:
        raise UnsafeUploadPathError("unsafe upload storage") from exc


def ensure_upload_root_safe(*, scan_tree: bool) -> Path:
    """Create the configured real directory and reject symlinks below it."""
    root = upload_root()
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        root.mkdir(parents=True, exist_ok=True)
        root_stat = _safe_lstat(root)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise UnsafeUploadPathError("unsafe upload storage")
    if not scan_tree:
        return root
    def fail_scan(exc):
        raise UnsafeUploadPathError("unsafe upload storage") from exc

    for directory, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=fail_scan
    ):
        base = Path(directory)
        for name in (*dirnames, *filenames):
            if stat.S_ISLNK(_safe_lstat(base / name).st_mode):
                raise UnsafeUploadPathError("unsafe upload storage")
    return root


def _relative_to_root(path: str | os.PathLike) -> tuple[Path, Path]:
    root = ensure_upload_root_safe(scan_tree=False)
    candidate = _absolute(path)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeUploadPathError("unsafe upload path") from exc
    return candidate, relative


def _assert_components_safe(
    path: Path,
    *,
    must_exist: bool,
    regular_target: bool,
    allow_missing_ancestors: bool = False,
) -> None:
    root = ensure_upload_root_safe(scan_tree=False)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafeUploadPathError("unsafe upload path") from exc
    current = root
    parts = relative.parts
    for index, part in enumerate(parts):
        current = current / part
        is_target = index == len(parts) - 1
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if allow_missing_ancestors or (is_target and not must_exist):
                return
            raise UnsafeUploadPathError("unsafe upload path")
        except OSError as exc:
            raise UnsafeUploadPathError("unsafe upload path") from exc
        if stat.S_ISLNK(mode):
            raise UnsafeUploadPathError("unsafe upload path")
        if not is_target and not stat.S_ISDIR(mode):
            raise UnsafeUploadPathError("unsafe upload path")
        if is_target and regular_target and not stat.S_ISREG(mode):
            raise UnsafeUploadPathError("unsafe upload path")


def _ensure_real_directory(path: Path) -> None:
    root = ensure_upload_root_safe(scan_tree=False)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafeUploadPathError("unsafe upload path") from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir()
            mode = _safe_lstat(current).st_mode
        except OSError as exc:
            raise UnsafeUploadPathError("unsafe upload path") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise UnsafeUploadPathError("unsafe upload path")


def _project_dir(project_id: int) -> Path:
    return upload_root() / str(project_id)


def validate_managed_file(
    file_path: str,
    project_id: int,
    *,
    must_exist: bool = True,
    allow_missing_ancestors: bool = False,
) -> Path:
    """Return a normalized upload path only when it is a non-symlink regular file."""
    path, relative = _relative_to_root(file_path)
    if not relative.parts or relative.parts[0] != str(project_id):
        raise UnsafeUploadPathError("unsafe upload path")
    _assert_components_safe(
        path,
        must_exist=must_exist,
        regular_target=must_exist,
        allow_missing_ancestors=allow_missing_ancestors,
    )
    return path


def reservation_paths(project_id: int, reservation_id: str, filename: str) -> tuple[Path, Path]:
    safe_name = safe_upload_name(filename)
    suffix = Path(safe_name).suffix
    directory = _project_dir(project_id) / ".pending"
    return directory / f"{reservation_id}.tmp", _project_dir(project_id) / f"{reservation_id}{suffix}"


def write_reserved_file(temp_path: str, target_path: str, data: bytes) -> None:
    """Exclusive temp write followed by fsync and atomic rename."""
    temp, temp_relative = _relative_to_root(temp_path)
    target, target_relative = _relative_to_root(target_path)
    if (
        len(temp_relative.parts) != 3
        or temp_relative.parts[1] != ".pending"
        or len(target_relative.parts) != 2
        or temp_relative.parts[0] != target_relative.parts[0]
    ):
        raise UnsafeUploadPathError("unsafe upload path")
    _ensure_real_directory(temp.parent)
    _ensure_real_directory(target.parent)
    _assert_components_safe(temp, must_exist=False, regular_target=False)
    _assert_components_safe(target, must_exist=False, regular_target=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("upload write made no progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _assert_components_safe(temp, must_exist=True, regular_target=True)
    _assert_components_safe(target.parent, must_exist=True, regular_target=False)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    os.replace(temp, target)


def safe_upload_name(filename: str) -> str:
    """업로드 파일명을 프로젝트 내부 상대경로로 정규화한다."""
    parts = []
    for part in filename.replace("\\", "/").split("/"):
        part = part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("invalid filename")
        parts.append(part)
    if not parts:
        raise ValueError("invalid filename")
    return "/".join(parts)


def delete_managed_file(file_path: str, project_id: int) -> None:
    path = validate_managed_file(
        file_path,
        project_id,
        must_exist=False,
        allow_missing_ancestors=True,
    )
    if path.exists():
        _assert_components_safe(path, must_exist=True, regular_target=True)
    path.unlink(missing_ok=True)
