"""Shared CLI approval detection; no process access, DB or runtime cache."""
import re

APPROVAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\(y/n\)", r"\[y/n\]", r"\by/n\b",
        r"do you want to proceed", r"do you approve",
        r"allow (?:this )?(?:execution|action|command|tool)",
        r"approve\?", r"proceed\?", r"confirm\?",
        r"allow once", r"allow for this session",
        r"permission required", r"requires? (?:your )?approval",
        r"would you like to (?:run|execute|proceed)",
        r"deseja continuar", r"aprovar\s*\?", r"confirmar\s*\?",
        r"❯\s*1\.\s*(yes|sim)", r"press enter to continue",
    ]
]

RESUMED_PATTERN = re.compile(
    r"(?:aplicando|continuando|executing|running command|conclu[ií]do|completed|finished)",
    re.IGNORECASE,
)



APPROVAL_PATTERNS.extend([
    re.compile(r'waiting for (?:input|approval)|aguardando (?:aprovação|entrada)|yes, (?:proceed|allow)', re.I),
])


def approval_lines(output: str) -> list[str]:
    recent = [line for line in output.splitlines() if line.strip()][-20:]
    matches = [i for i, line in enumerate(recent)
        if any(pattern.search(line) for pattern in APPROVAL_PATTERNS)]
    if not matches:
        return []
    last = matches[-1]
    if RESUMED_PATTERN.search('\n'.join(recent[last + 1:])):
        return []
    return recent[max(0, last - 2):]
