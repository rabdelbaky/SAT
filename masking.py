"""Secret masking for Pre-LLM Checks.

Public API
----------
mask_secrets(text) -> str
    Return *text* with secrets replaced by ``***``: Bearer tokens, API keys,
    passwords, connection-string credentials and common env-var assignments.

Its own module so runner.py and pre_llm_checks.py can both import it without
a circular import (pre_llm_checks imports orchestrator, which imports runner).

Cross-platform: Python 3.11+, no third-party packages.
"""

from __future__ import annotations

import re

# Patterns that identify secrets. Each pattern replaces the captured value
# group (group 1) with "***".
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Bearer / token headers
    re.compile(r"(Bearer\s+)\S+", re.IGNORECASE),
    # KEY=value or TOKEN=value assignments (env-var style)
    re.compile(
        r"(?i)((?:api[_\-]?key|secret[_\-]?key|access[_\-]?key|auth[_\-]?token|"
        r"api[_\-]?secret|password|passwd|token|aws[_\-]access[_\-]key(?:[_\-]id)?|"
        r"private[_\-]?key)\s*[:=]\s*)\S+",
    ),
    # URL with password: scheme://user:password@host
    re.compile(r"(://[^:/@\s]+:)[^@\s]+(@)", re.IGNORECASE),
    # Query-string api_key / apikey / token params
    re.compile(r"(?i)([?&](?:api_key|apikey|token|secret|password)=)[^\s&\"']+"),
]


def mask_secrets(text: str) -> str:
    """Return *text* with secrets replaced by ``***``.

    Covers: Bearer tokens, API keys, passwords, connection-string credentials,
    and common env-var assignments.
    """
    for pattern in _SECRET_PATTERNS:
        # Replace only the value portion (captured groups) while keeping
        # surrounding syntax (e.g. "Bearer ", "TOKEN=", "://user:").
        # We use a lambda so we can reconstruct the non-secret parts.
        def _replace(m: re.Match[str], _p: re.Pattern[str] = pattern) -> str:
            groups = m.groups()
            if not groups:
                return "***"
            full = m.group(0)
            result = full
            # For patterns with a trailing group (e.g. the "@" in URL passwords)
            # we need to preserve prefix + suffix around the secret.
            if len(groups) == 1:
                result = groups[0] + "***"
            elif len(groups) == 2:
                result = groups[0] + "***" + groups[1]
            return result

        text = pattern.sub(_replace, text)
    return text
