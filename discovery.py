"""Project discovery for Pre-LLM Checks (Session 4).

Public API
----------
discover_projects(root, languages) -> list[Project]
solution_projects(solution) -> set[Path]

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
    - Exception: a Maven module or Gradle subproject is built by its root
      build, so it is part of the root project, not a project of its own.
      Data-driven: languages.toml ``subproject_rules`` maps the root's
      primary build file to a rule (``maven_modules``: the root pom.xml lists
      the folder in <module>; ``gradle_settings``: the root folder has a
      settings.gradle(.kts) and the sub-folder has none; ``dotnet_solution``:
      the root .sln/.slnx lists the sub-folder's .csproj).  A rule key may be
      a glob (``"*.sln"``).
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
import re
import xml.etree.ElementTree as ET
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

    projects = _drop_subprojects(projects, languages)
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


_GRADLE_SETTINGS = ("settings.gradle", "settings.gradle.kts")


def _maven_modules(pom: Path) -> set[Path]:
    """Return the resolved folders a pom.xml lists in <module> (any profile).

    Read-only.  An unreadable or invalid pom lists nothing.  A module entry
    may name a folder or a pom file inside it.
    """
    try:
        tree = ET.parse(pom)
    except (OSError, ET.ParseError):
        return set()
    folders: set[Path] = set()
    for elem in tree.iter():
        tag = elem.tag.rsplit("}", 1)[-1] if isinstance(elem.tag, str) else ""
        if tag != "module" or not elem.text or not elem.text.strip():
            continue
        target = pom.parent / elem.text.strip()
        if target.suffix == ".xml":
            target = target.parent
        folders.add(target.resolve())
    return folders


# Project("{type GUID}") = "Name", "relative\path.csproj", "{project GUID}"
_SLN_PROJECT_RE = re.compile(r'^\s*Project\("[^"]*"\)\s*=\s*"[^"]*"\s*,\s*"([^"]*)"', re.MULTILINE)


def solution_projects(solution: Path) -> set[Path]:
    """Return the resolved paths of the .csproj files a .sln or .slnx lists.

    Read-only.  ``.sln``: the second quoted value of each ``Project(...)``
    line (backslashes become slashes).  ``.slnx``: the ``Path`` attribute of
    every ``Project`` element at any depth.  Solution folders also appear as
    projects, so only paths ending ``.csproj`` are kept.  An unreadable or
    invalid file lists nothing.
    """
    try:
        # dotnet new sln writes a BOM.
        text = solution.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return set()
    if solution.suffix == ".slnx":
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return set()
        paths = [
            elem.get("Path", "")
            for elem in root.iter()
            if isinstance(elem.tag, str) and elem.tag.rsplit("}", 1)[-1] == "Project"
        ]
    else:
        paths = _SLN_PROJECT_RE.findall(text)
    return {
        (solution.parent / p.replace("\\", "/")).resolve()
        for p in paths
        if p.endswith(".csproj")
    }


def _is_subproject_of(child: Project, root: Project, rule: str) -> bool:
    """Return True if *root*'s own build builds *child* (see subproject_rules)."""
    if rule == "maven_modules":
        return (
            child.primary_build_file == "pom.xml"
            and child.path.resolve() in _maven_modules(root.path / root.primary_build_file)
        )
    if rule == "gradle_settings":
        return (
            child.primary_build_file.startswith("build.gradle")
            and any((root.path / n).is_file() for n in _GRADLE_SETTINGS)
            and not any((child.path / n).is_file() for n in _GRADLE_SETTINGS)
        )
    if rule == "dotnet_solution":
        return (child.path / child.primary_build_file).resolve() in solution_projects(
            root.path / root.primary_build_file
        )
    return False


def _rule_for(rules: dict, build_file: str) -> str | None:
    """Return the subproject rule for *build_file*: exact key first, then a glob key."""
    if build_file in rules:
        return rules[build_file]
    for key, rule in rules.items():
        if fnmatch.fnmatch(build_file, key):
            return rule
    return None


def _drop_subprojects(projects: list[Project], languages: dict) -> list[Project]:
    """Remove Maven modules / Gradle subprojects that a root project builds.

    A project is dropped when another project of the same language in an
    ancestor folder claims it under that language's ``subproject_rules``
    (keyed by the ancestor's primary build file; with no exact key, the
    first key that is a matching glob, e.g. ``"*.sln"``).  Nested modules
    work pair by pair: root -> a, a -> a/b.
    """
    kept: list[Project] = []
    for child in projects:
        rules: dict = languages.get(child.language, {}).get("subproject_rules", {})
        claimed = False
        if rules:
            child_path = child.path.resolve()
            for root in projects:
                rule = _rule_for(rules, root.primary_build_file)
                if (
                    rule
                    and root.language == child.language
                    and root.path.resolve() in child_path.parents
                    and _is_subproject_of(child, root, rule)
                ):
                    claimed = True
                    break
        if not claimed:
            kept.append(child)
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
