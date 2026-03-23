from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


REPO_URLS = {
    "testpypi": "https://test.pypi.org/legacy/",
    "pypi": "https://upload.pypi.org/legacy/",
}


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def _ensure_tool_exists(tool: str) -> None:
    if shutil.which(tool) is None:
        raise RuntimeError(
            f"Missing required tool: {tool}. Install it in your release environment "
            f"(e.g. `python3 -m pip install build twine`)."
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build and publish AgentOps framework.")
    parser.add_argument(
        "--target",
        choices=["testpypi", "pypi"],
        default="testpypi",
        help="Upload destination.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip local test scripts (useful if deps are not installed).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run, but do not execute build/upload.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    if not args.skip_tests:
        # Best-effort: these scripts validate core behavior, but may require
        # optional third-party deps (google-genai, langgraph, etc.).
        # They should be run in the same environment used for `pip install -r requirements.txt`.
        scripts = [
            repo_root / "tests" / "test_phase0.py",
            repo_root / "tests" / "test_phase1.py",
            repo_root / "tests" / "test_phase2.py",
            repo_root / "tests" / "test_phase3.py",
            repo_root / "tests" / "test_review_fixes.py",
        ]
        for s in scripts:
            print(f"Running test script: {s}")
            _run([sys.executable, str(s)], cwd=repo_root)

    # `python -m build` uses the build module (no executable lookup needed).
    try:
        __import__("build")
    except Exception as e:
        raise RuntimeError(
            "Missing required module: `build`. Install it in your release environment "
            "(e.g. `python3 -m pip install build`)."
        ) from e

    _ensure_tool_exists("twine")

    # Build artifacts
    if args.dry_run:
        print("Dry-run enabled: skipping build/upload commands.")
        return

    dist_dir = repo_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Clean dist to avoid uploading stale artifacts
    for p in dist_dir.glob("*"):
        if p.is_file():
            p.unlink()

    _run([sys.executable, "-m", "build"], cwd=repo_root)

    repo_url = REPO_URLS[args.target]
    _run(
        [
            "twine",
            "upload",
            "--repository-url",
            repo_url,
            str(dist_dir / "*"),
        ],
        cwd=repo_root,
    )

    print(f"Publish complete to: {args.target} ({repo_url})")


if __name__ == "__main__":
    main()

