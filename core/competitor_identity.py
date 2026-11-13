from __future__ import annotations

RENAME_MAP = {
    "凌水球知道": "DUT星球",
}

MATRIX_NAME = "DUT/NEU/求是矩阵"

MATRIX_MEMBERS = {
    "DUT星球": MATRIX_NAME,
    "NEU星球": MATRIX_NAME,
    "求是情报站": MATRIX_NAME,
}


def canonicalize_competitor_name(name: str) -> str:
    raw = (name or "").strip()
    return RENAME_MAP.get(raw, raw)


def competitor_matrix_name(name: str) -> str | None:
    canonical = canonicalize_competitor_name(name)
    return MATRIX_MEMBERS.get(canonical)
