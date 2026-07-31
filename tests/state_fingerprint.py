#!/usr/bin/env python3
"""검증 로그를 현재 Git 작업 트리에 결속하는 읽기 전용 지문 도구.

직렬화의 정본은 이 파일이다. 이 도구는 Git index나 작업 트리를 수정하지 않으며
digest 한 줄만 stdout에 출력한다.
"""

import argparse
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Set


def _git(repo: bytes, *args: bytes) -> bytes:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return subprocess.run(
        [b"git", b"-C", repo, *args],
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _record(kind: bytes, path: bytes, payload: bytes) -> bytes:
    return b"".join(
        (
            kind,
            b"\n",
            str(len(path)).encode("ascii"),
            b"\n",
            path,
            b"\n",
            str(len(payload)).encode("ascii"),
            b"\n",
            payload,
            b"\n",
        )
    )


def _canonical_relative_path(value: str) -> bytes:
    raw = os.fsencode(value)
    parts = raw.split(b"/")
    if not raw or raw.startswith(b"/") or any(part in {b"", b".", b".."} for part in parts):
        raise ValueError(
            f"제외 경로는 정규화된 repo-relative path여야 한다: {value!r}"
        )
    return raw


def _repository_root(repo: Path) -> bytes:
    requested = os.fsencode(os.fspath(repo))
    output = _git(requested, b"rev-parse", b"--show-toplevel")
    if not output.endswith(b"\n") or output.endswith(b"\n\n"):
        raise RuntimeError("git rev-parse --show-toplevel 출력 형식이 예상과 다르다")
    return output[:-1]


def _head_payload(repo: bytes) -> bytes:
    output = _git(repo, b"rev-parse", b"--verify", b"HEAD")
    if not output.endswith(b"\n") or output.endswith(b"\n\n"):
        raise RuntimeError("git rev-parse HEAD 출력 형식이 예상과 다르다")
    return output[:-1]


def _diff_payload(repo: bytes) -> bytes:
    # 사용자 Git 설정이 patch bytes를 바꾸지 못하도록 출력 관련 옵션을 고정한다.
    return _git(
        repo,
        b"-c",
        b"core.quotePath=true",
        b"diff",
        b"--binary",
        b"--no-color",
        b"--no-ext-diff",
        b"--no-textconv",
        b"--no-renames",
        b"--diff-algorithm=myers",
        b"--no-indent-heuristic",
        b"--src-prefix=a/",
        b"--dst-prefix=b/",
        b"HEAD",
        b"--",
    )


def _untracked_records(repo: bytes, excluded: Set[bytes]) -> List[bytes]:
    output = _git(repo, b"ls-files", b"-z", b"--others", b"--exclude-standard", b"--")
    paths = output.split(b"\0")
    if paths[-1] != b"":
        raise RuntimeError("git ls-files -z 출력에 종단 NUL이 없다")

    records: List[tuple[bytes, bytes]] = []
    for path in paths[:-1]:
        if path in excluded:
            continue

        absolute = os.path.join(repo, path)
        metadata = os.lstat(absolute)
        if stat.S_ISLNK(metadata.st_mode):
            payload = os.readlink(absolute)
            if isinstance(payload, str):  # bytes 경로를 넘겼으므로 방어적 처리다.
                payload = os.fsencode(payload)
            record = _record(b"link", path, payload)
        elif stat.S_ISREG(metadata.st_mode):
            mode = format(stat.S_IMODE(metadata.st_mode), "04o").encode("ascii")
            content_hash = hashlib.sha256()
            with open(absolute, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content_hash.update(chunk)
            payload = mode + b" " + content_hash.hexdigest().encode("ascii")
            record = _record(b"file", path, payload)
        else:
            display = os.fsdecode(path)
            raise RuntimeError(f"지원하지 않는 untracked 객체 형식: {display!r}")
        records.append((path, record))

    records.sort(key=lambda item: item[0])
    return [record for _, record in records]


def fingerprint(repo: Path, excluded_paths: List[str]) -> str:
    root = _repository_root(repo)
    excluded = {_canonical_relative_path(path) for path in excluded_paths}

    digest = hashlib.sha256()
    digest.update(_record(b"head", b"", _head_payload(root)))
    digest.update(_record(b"diff", b"", _diff_payload(root)))
    for record in _untracked_records(root, excluded):
        digest.update(record)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Git 저장소 내부 경로(기본값: 현재 디렉터리)",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        metavar="REPO_RELATIVE_PATH",
        help="지문에서 제외할 정확한 repo-relative untracked 경로(반복 가능)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        print(fingerprint(args.repo, args.exclude_path))
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"state fingerprint 계산 실패: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
