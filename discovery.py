"""Project discovery for Pre-LLM Checks (Session 4).

Public API
----------
discover_projects(root, languages) -> list[Project]

    Walk *root*, skipping the folders listed in SKIP_DIRS, and return one
    Project per (folder, language) pair where at least one build file for
    that language exists.

    Rules (SPEC §3 steps 1–2):
    - Skip: node_modules, .git, .next, target, build, dist, .venv,
      graphify-out, .ua, .pre-llm, bin, obj, venv, env, vendor, out,
      __pycache__, coverage.
    - A build file owns only files of its own language.
    - Each file belongs to the nearest build file above it (sub-project wins
      over root). discover_projects does not assign files to projects; that is
      the concern of later stages.
    - One project per folder per language.  When a folder has multiple build
      files for the same language, the priority list in languages.toml
      determines the primary build file; all matching build files are kept in
      Project.build_files.
    - Languages and build files come from languages.toml (passed in as
      *languages* dict), not hard-coded.

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Skip list (SPEC §3 step 2)
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".next",
        "target",
        "build",
        "dist",
        ".venv",
        "graphify-out",
        ".ua",
        ".pre-llm",
        "bin",
        "obj",
        "venv",
        "env",
        "vendor",
        "out",
        "__pycache__",
        "coverage",
    }
)


# ---------------------------------------------------------------------------
# Project dataclass
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """One discovered project: a folder that contains build file(s) for one language."""

    path: Path
    language: str
    primary_build_file: str
    build_files: list[str] = field(default_factory=list)
    tested: bool = False

    def __post_init__(self) -> None:
        # Guarantee primary is always listed in build_files
        if self.primary_build_file not in self.build_files:
            self.build_files.insert(0, self.primary_build_file)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _match_build_files(folder: Path, patterns: list[str]) -> list[str]:
    """Return names of files in *folder* that match any of *patterns*.

    Patterns are either plain filenames (``"package.json"``) or simple globs
    (``"*.sln"``, ``"*.csproj"``).  Matching is case-sensitive on all
    platforms (build-tool filenames are conventionally lowercase or
    CamelCase; case-folding would introduce false positives on case-sensitive
    filesystems).
    """
    try:
        entries = [e.name for e in folder.iterdir() if e.is_file()]
    except PermissionError:
        return []

    matched: list[str] = []
    for pattern in patterns:
        for name in entries:
            if fnmatch.fnmatch(name, pattern) and name not in matched:
                matched.append(name)
    return matched


def _primary_build_file(
    present: list[str],
    priority: list[str],
) -> str:
    """Return the highest-priority build file name from *present*.

    *priority* is an ordered list of patterns (plain names or globs) from
    languages.toml.  The first pattern that matches any name in *present*
    wins.  Falls back to the first element of *present* if nothing matches.
    """
    for pattern in priority:
        for name in present:
            if fnmatch.fnmatch(name, pattern):
                return name
    return present[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_projects(
    root: Path,
    languages: dict,
    ignore: list[str] | None = None,
) -> list[Project]:
    """Walk *root* and return one Project per (folder, language) pair found.

    Parameters
    ----------
    root:
        Absolute path to the repository root (or any folder to scan).
    languages:
        The dict returned by ``load_languages()``.  Keys are language names;
        values contain at least ``build_files`` (list[str]) and
        ``build_priority`` (list[str]), and ``tested`` (bool).
    ignore:
        Optional list of folder names (relative to *root*) to skip, as read
        from pre-llm.toml ``ignore``.  These are added to the built-in
        SKIP_DIRS for this walk only.

    Returns
    -------
    list[Project]
        Projects sorted by (path, language) for deterministic output.
        Returns an empty list if no supported build files are found.
    """
    extra_skip: frozenset[str] = frozenset(ignore) if ignore else frozenset()
    projects: list[Project] = []

    for folder, dirnames, _ in _walk_skipping(root, extra_skip=extra_skip):
        folder_path = Path(folder)
        found: list[Project] = []

        for lang_name, lang_cfg in languages.items():
            bf_patterns: list[str] = lang_cfg.get("build_files", [])
            priority: list[str] = lang_cfg.get("build_priority", bf_patterns)
            tested: bool = lang_cfg.get("tested", False)

            present = _match_build_files(folder_path, bf_patterns)
            if not present:
                continue

            primary = _primary_build_file(present, priority)
            found.append(
                Project(
                    path=folder_path,
                    language=lang_name,
                    primary_build_file=primary,
                    build_files=present,
                    tested=tested,
                )
            )

        projects.extend(_resolve_shared_build_files(found, languages, extra_skip))

    projects.sort(key=lambda p: (str(p.path), p.language))
    return projects


# Gradle scripts (build.gradle.kts, settings.gradle.kts) end in .kts but are
# build files, not Kotlin sources.
_BUILD_SCRIPT_SUFFIXES = (".gradle", ".gradle.kts")


def _has_sources(folder: Path, extensions: list[str], extra_skip: frozenset[str]) -> bool:
    """Return True if *folder* contains a source file with one of *extensions*.

    Skipped folders and build scripts do not count.
    """
    wanted = tuple(extensions)
    for _, _, filenames in _walk_skipping(folder, extra_skip=extra_skip):
        for name in filenames:
            if name.endswith(wanted) and not name.endswith(_BUILD_SCRIPT_SUFFIXES):
                return True
    return False


def _resolve_shared_build_files(
    found: list[Project],
    languages: dict,
    extra_skip: frozenset[str],
) -> list[Project]:
    """Resolve languages that claim the same primary build file in one folder.

    java and kotlin both list build.gradle(.kts).  Keep the languages that have
    source files of their own extensions; if none do, keep the first declared.
    """
    by_primary: dict[str, list[Project]] = {}
    for p in found:
        by_primary.setdefault(p.primary_build_file, []).append(p)

    kept: list[Project] = []
    for group in by_primary.values():
        if len(group) == 1:
            kept.extend(group)
            continue
        with_sources = [
            p
            for p in group
            if _has_sources(p.path, languages[p.language].get("extensions", []), extra_skip)
        ]
        kept.extend(with_sources or group[:1])
    return kept


def _walk_skipping(root: Path, extra_skip: frozenset[str] = frozenset()):
    """os.walk equivalent that skips SKIP_DIRS and *extra_skip* in-place.

    Yields (dirpath_str, dirnames, filenames) just like os.walk, but never
    descends into any directory whose name is in SKIP_DIRS or *extra_skip*.
    """
    import os

    combined = SKIP_DIRS | extra_skip
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk does not descend into them.
        dirnames[:] = [d for d in dirnames if d not in combined]
        yield dirpath, dirnames, filenames
