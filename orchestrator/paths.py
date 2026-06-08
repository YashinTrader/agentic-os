"""Path helpers for orchestrator CLI and tests — no LangGraph dependency."""

from __future__ import annotations

from pathlib import Path


def resolve_output_dir(
    repo_root: Path,
    output_dir: str | None,
    *,
    allow_outside_repo: bool = False,
) -> str:
    """Resolve orchestrator output directory inside repo root by default."""
    default = repo_root / "runtime" / "orchestrator" / "runs"
    if output_dir is None:
        return str(default.resolve())

    candidate = Path(output_dir)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (repo_root / candidate).resolve()

    if ".." in candidate.parts:
        raise ValueError(
            f"output directory must not contain path traversal segments: {output_dir}"
        )

    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        if not allow_outside_repo:
            raise ValueError(
                f"output directory must be inside repository root ({repo_root}); "
                f"got {resolved}. Pass --allow-outside-repo only for explicit override."
            ) from exc

    return str(resolved)