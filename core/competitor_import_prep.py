from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

from core.competitor_identity import canonicalize_competitor_name

EXPECTED_COLUMNS = [
    "nickname",
    "title",
    "url",
    "time",
    "like_num",
    "read_num",
    "share_num",
    "comment_count",
]

PLACEHOLDER_NICKNAMES = {"公众号"}


def prepare_competitor_csv_texts(file_entries, output_dir: str | Path, fallback_name: str = "") -> dict:
    entries = []
    for filename, content in file_entries:
        rows = _parse_csv_text(content, filename)
        entries.append((filename, rows))
    return _prepare_entries(entries, output_dir, fallback_name=fallback_name)


def prepare_competitor_csv_paths(paths, output_dir: str | Path, fallback_name: str = "") -> dict:
    entries = []
    for path in sorted(Path(p) for p in paths):
        rows = _parse_csv_text(path.read_text(encoding="utf-8-sig"), path.name)
        entries.append((path.name, rows))
    return _prepare_entries(entries, output_dir, fallback_name=fallback_name)


def normalize_folder_nickname(folder_name: str) -> str:
    name = (folder_name or "").strip()
    name = re.sub(r"^链接\d+-", "", name)
    name = re.sub(r"-下载完成$", "", name)
    name = re.sub(r"-\d+$", "", name)
    return canonicalize_competitor_name(name.strip())


def _prepare_entries(entries, output_dir: str | Path, fallback_name: str = "") -> dict:
    if not entries:
        raise ValueError("未上传文件")

    total_rows = 0
    all_names = set()
    latest_by_key = {}

    for source_name, rows in entries:
        for row in rows:
            total_rows += 1
            nickname = (row.get("nickname") or "").strip()
            if nickname:
                all_names.add(nickname)
            key = _dedupe_key(row)
            existing = latest_by_key.get(key)
            if existing is None or _parse_time(row.get("time")) >= _parse_time(existing.get("time")):
                latest_by_key[key] = row

    nickname = _resolve_nickname(
        all_names,
        fallback_name=fallback_name,
        source_names=[name for name, _ in entries],
    )
    deduped_rows = sorted(
        latest_by_key.values(),
        key=lambda row: (_parse_time(row.get("time")), row.get("title", ""), row.get("url", "")),
        reverse=True,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_filename = _build_prepared_filename(nickname, [name for name, _ in entries])
    prepared_path = output_dir / prepared_filename
    _write_prepared_csv(prepared_path, deduped_rows, nickname)

    articles = [
        {
            "title": row.get("title", "").strip(),
            "url": row.get("url", "").strip(),
            "publish_time": row.get("time", "").strip(),
            "like_num": _to_int(row.get("like_num")),
            "read_num": _to_int(row.get("read_num")),
            "share_num": _to_int(row.get("share_num")),
            "comment_count": _to_int(row.get("comment_count")),
        }
        for row in deduped_rows
    ]

    return {
        "nickname": nickname,
        "articles": articles,
        "source_files": len(entries),
        "total_rows": total_rows,
        "deduped_rows": len(deduped_rows),
        "prepared_filename": prepared_filename,
        "prepared_path": str(prepared_path),
    }


def _parse_csv_text(content: str, source_name: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames != EXPECTED_COLUMNS:
        raise ValueError(f"{source_name} 表头不正确")
    rows = []
    for row in reader:
        rows.append({key: (row.get(key, "") or "").strip() for key in EXPECTED_COLUMNS})
    if not rows:
        raise ValueError(f"{source_name} 文件为空")
    return rows


def _resolve_nickname(names: set[str], fallback_name: str = "", source_names: list[str] | None = None) -> str:
    real_names = sorted(name for name in names if name and name not in PLACEHOLDER_NICKNAMES)
    if len(real_names) > 1:
        raise ValueError(f"检测到多个真实公众号名: {'、'.join(real_names)}")
    if len(real_names) == 1:
        return canonicalize_competitor_name(real_names[0])

    fallback_name = normalize_folder_nickname(fallback_name)
    if fallback_name and fallback_name not in PLACEHOLDER_NICKNAMES:
        return canonicalize_competitor_name(fallback_name)

    inferred_name = infer_nickname_from_source_names(source_names or [])
    if inferred_name and inferred_name not in PLACEHOLDER_NICKNAMES:
        return canonicalize_competitor_name(inferred_name)

    if names:
        return canonicalize_competitor_name(sorted(names)[0])
    raise ValueError("未识别到公众号名")


def infer_nickname_from_source_names(source_names: list[str]) -> str:
    candidates = {
        candidate
        for candidate in (_infer_nickname_from_source_name(name) for name in source_names)
        if candidate and candidate not in PLACEHOLDER_NICKNAMES
    }
    if len(candidates) == 1:
        return canonicalize_competitor_name(next(iter(candidates)))
    return ""


def _infer_nickname_from_source_name(source_name: str) -> str:
    stem = Path(source_name).stem.strip()
    match = re.match(r"^(?P<nickname>.+?)_(?=\d{4}-\d{2}-\d{2})", stem)
    if not match:
        return ""
    return canonicalize_competitor_name(match.group("nickname").strip())


def _build_prepared_filename(nickname: str, source_names: list[str]) -> str:
    stems = sorted(Path(name).stem for name in source_names)
    if len(stems) == 1:
        tail = stems[0]
        if not re.search(r"merged[_-]dedup$", tail):
            tail = f"{tail}_merged_dedup"
    else:
        tail = f"{stems[0]}_to_{stems[-1]}_merged_dedup"
    safe_nickname = _sanitize_filename(nickname)
    if not tail.startswith(f"{safe_nickname}_"):
        tail = f"{safe_nickname}_{tail}"
    return f"{tail}.csv"


def _write_prepared_csv(path: Path, rows: list[dict], nickname: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        for row in rows:
            record = dict(row)
            record["nickname"] = nickname
            writer.writerow({key: record.get(key, "") for key in EXPECTED_COLUMNS})


def _dedupe_key(row: dict) -> str:
    url = (row.get("url") or "").strip()
    if url:
        return url
    return f"title::{(row.get('title') or '').strip()}"


def _parse_time(value: str | None) -> datetime:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.min


def _to_int(value) -> int:
    try:
        return int(str(value).strip()) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def _sanitize_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "", value)
