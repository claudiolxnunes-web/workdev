#!/usr/bin/env python3

import json
import hashlib
import re
from pathlib import Path
from collections import Counter

ROOT = Path("/opt/workdev/training/workdev-master-v2")
PATHS_FILE = ROOT / "datasets/raw/session-paths-unique.txt"
OUTPUT = ROOT / "datasets/candidates.jsonl"
REJECTED = ROOT / "datasets/raw/rejected-candidates.jsonl"

MAX_USER_CHARS = 30000
MAX_ASSISTANT_CHARS = 30000
MIN_CHARS = 2

SYSTEM_NOISE_PATTERNS = [
    r"<system-reminder>",
    r"<skills_instructions>",
    r"<multi_agent_role>",
    r"<multi_agent_mode>",
    r"<environment_context>",
    r"^# AGENTS\.md instructions",
]

def source_from_path(path):
    p = str(path)
    if "/.claude/" in p:
        return "claude"
    if "/.codex/" in p:
        return "codex"
    if "/.kimi-code/" in p:
        return "kimi"
    if "/.qwen/" in p:
        return "qwen"
    return "unknown"

def is_noise(text):
    if not text:
        return True
    s = text.strip()
    if len(s) < MIN_CHARS:
        return True
    for pat in SYSTEM_NOISE_PATTERNS:
        if re.search(pat, s, flags=re.I | re.M):
            return True
    return False

def flatten_content(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue

            if not isinstance(item, dict):
                continue

            typ = item.get("type")

            if typ in ("text", "input_text", "output_text"):
                txt = item.get("text")
                if isinstance(txt, str):
                    parts.append(txt)

        return "\n".join(x for x in parts if x).strip()

    return ""

def extract_claude(obj):
    typ = obj.get("type")
    if typ not in ("user", "assistant"):
        return None

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None

    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None

    text = flatten_content(msg.get("content"))
    return role, text

def extract_qwen(obj):
    typ = obj.get("type")
    if typ not in ("user", "assistant"):
        return None

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None

    role = msg.get("role") or typ
    if role not in ("user", "assistant"):
        return None

    content = msg.get("parts", msg.get("content"))
    text = flatten_content(content)
    return role, text

def extract_codex(obj):
    if obj.get("type") != "response_item":
        return None

    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None

    if payload.get("type") != "message":
        return None

    role = payload.get("role")
    if role not in ("user", "assistant"):
        return None

    # Comentários intermediários do agente não viram resposta de treino.
    if role == "assistant":
        phase = payload.get("phase")
        if phase == "commentary":
            return None

    text = flatten_content(payload.get("content"))
    return role, text

def extract_kimi(obj):
    typ = obj.get("type")

    if typ == "turn.prompt":
        text = flatten_content(obj.get("input"))
        return "user", text

    if typ != "context.append_message":
        return None

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None

    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None

    # Injeções internas do runtime Kimi não são fala real do usuário.
    origin = msg.get("origin")
    if isinstance(origin, dict) and origin.get("kind") == "injection":
        return None

    text = flatten_content(msg.get("content"))
    return role, text

EXTRACTORS = {
    "claude": extract_claude,
    "codex": extract_codex,
    "kimi": extract_kimi,
    "qwen": extract_qwen,
}

def normalize(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()

def pair_hash(user, assistant):
    raw = (user.strip() + "\n<<<A>>>\n" + assistant.strip()).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def category_guess(user, assistant):
    blob = (user + "\n" + assistant).lower()

    review_terms = [
        "review", "revis", "diff", "gate", "finding",
        "approve", "aprova", "valida", "teste",
    ]
    code_terms = [
        ".py", ".tsx", ".ts", ".js", "fastapi", "react",
        "pytest", "pnpm", "git ", "websocket", "endpoint",
        "migration", "router", "service", "function", "class ",
    ]
    behavior_terms = [
        "não invent", "nao invent", "evidência", "evidencia",
        "contexto", "runtime", "persist", "bloque", "waiting_input",
    ]

    if any(x in blob for x in review_terms):
        return "review"
    if any(x in blob for x in code_terms):
        return "code"
    if any(x in blob for x in behavior_terms):
        return "behavior"
    return "uncategorized"

def reject(reason, source, path, role=None, text=None):
    return {
        "reason": reason,
        "source": source,
        "path": str(path),
        "role": role,
        "text_preview": (text or "")[:500],
    }

def main():
    paths = [
        Path(x.strip())
        for x in PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]

    output_rows = []
    rejected = []
    stats = Counter()
    seen_pairs = set()

    for path in paths:
        source = source_from_path(path)
        extractor = EXTRACTORS.get(source)

        if not extractor:
            stats["unknown_source"] += 1
            continue

        if not path.exists():
            rejected.append(reject("missing_file", source, path))
            stats["missing_file"] += 1
            continue

        messages = []

        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                try:
                    obj = json.loads(line)
                except Exception:
                    stats["invalid_json"] += 1
                    continue

                extracted = extractor(obj)
                if not extracted:
                    continue

                role, text = extracted
                text = normalize(text)

                if is_noise(text):
                    rejected.append(
                        reject("noise", source, path, role, text)
                    )
                    stats["noise"] += 1
                    continue

                if role == "user" and len(text) > MAX_USER_CHARS:
                    rejected.append(
                        reject("user_too_large", source, path, role, text)
                    )
                    stats["user_too_large"] += 1
                    continue

                if role == "assistant" and len(text) > MAX_ASSISTANT_CHARS:
                    rejected.append(
                        reject("assistant_too_large", source, path, role, text)
                    )
                    stats["assistant_too_large"] += 1
                    continue

                messages.append((role, text, line_no))

        # Compacta mensagens consecutivas do mesmo papel.
        compact = []
        for role, text, line_no in messages:
            if compact and compact[-1][0] == role:
                old_role, old_text, old_line = compact[-1]
                joined = old_text + "\n\n" + text

                limit = MAX_USER_CHARS if role == "user" else MAX_ASSISTANT_CHARS
                if len(joined) <= limit:
                    compact[-1] = (old_role, joined, old_line)
                else:
                    compact.append((role, text, line_no))
            else:
                compact.append((role, text, line_no))

        # Forma pares user -> assistant.
        i = 0
        while i < len(compact) - 1:
            role1, text1, line1 = compact[i]
            role2, text2, line2 = compact[i + 1]

            if role1 == "user" and role2 == "assistant":
                h = pair_hash(text1, text2)

                if h not in seen_pairs:
                    seen_pairs.add(h)

                    row = {
                        "source": source,
                        "category": category_guess(text1, text2),
                        "source_file": str(path),
                        "source_lines": [line1, line2],
                        "messages": [
                            {"role": "user", "content": text1},
                            {"role": "assistant", "content": text2},
                        ],
                        "sha256": h,
                    }

                    output_rows.append(row)
                    stats[f"pairs_{source}"] += 1
                    stats[f"category_{row['category']}"] += 1
                else:
                    stats["duplicate_pair"] += 1

                i += 2
            else:
                i += 1

    with OUTPUT.open("w", encoding="utf-8") as f:
        for row in output_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with REJECTED.open("w", encoding="utf-8") as f:
        for row in rejected:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("=== EXTRAÇÃO CONCLUÍDA ===")
    print("arquivos analisados:", len(paths))
    print("candidatos únicos:", len(output_rows))
    print()

    print("Por agente:")
    for name in ("claude", "codex", "kimi", "qwen"):
        print(f"  {name:7}: {stats[f'pairs_{name}']}")

    print()
    print("Por categoria:")
    for name in ("code", "review", "behavior", "uncategorized"):
        print(f"  {name:14}: {stats[f'category_{name}']}")

    print()
    print("Descartes:")
    for key in (
        "noise",
        "user_too_large",
        "assistant_too_large",
        "duplicate_pair",
        "invalid_json",
        "missing_file",
    ):
        print(f"  {key:20}: {stats[key]}")

    print()
    print("Saída:", OUTPUT)
    print("Rejeitados:", REJECTED)

if __name__ == "__main__":
    main()
