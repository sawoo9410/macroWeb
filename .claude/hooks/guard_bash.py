#!/usr/bin/env python3
"""PreToolUse(Bash) guard (PLAN §13.4, CLAUDE.md 불변 규칙 7–8). Reads the tool call as JSON on stdin and
answers with `hookSpecificOutput.permissionDecision` deny/ask (exit 0), or stays silent to allow.
Hooks also fire inside subagents with `agent_type` set, which lets us keep fact-checker read-only.

Heredoc bodies (`cat > f <<'EOF' ... EOF`) are data, not commands: they are stripped before matching so that
writing documentation that *mentions* `private/.env` is not mistaken for reading it (lesson from the Phase 0
session, where the first version of this guard blocked its own repo scaffolding).

Stdlib only; must run on the system python3 (3.9+). Decisions are appended to logs/hooks.jsonl."""

import json
import os
import re
import sys
import time

SECRET_PATH = re.compile(
    r"private/(?!README\.md\b|env\.example\b)|(?<![\w.-])\.env(?![\w.-]*example)|token[\w-]*\.json|\.credentials\.json|~/\.ssh/|\.ssh/id_"
)
READER = re.compile(
    r"(^|[\s;&|(`$])(cat|head|tail|less|more|sed|awk|grep|rg|egrep|fgrep|bat|strings|xxd|hexdump|od|base64|open|code|vim|vi|nano|emacs|python3?|uv|jq|yq|source|cp|scp|rsync|mv|tar|zip|gzip|curl|wget|tee|cut|sort|uniq|tr|paste|xargs|perl|ruby|node|php|security)\b"
)
DOT_SOURCE = re.compile(r"(^|[\s;&|(])\.\s+\S*(private/|\.env)")
INPUT_REDIRECT = re.compile(r"<\s*\S*(private/|\.env)")
ENV_DUMP = re.compile(
    r"(^|[\s;&|(])(printenv\b|env(\s*($|[;&|)]))|set(\s*($|[;&|)]))|declare\s+-p|export\s+-p)"
)
ECHO_SECRET = re.compile(
    r"\becho\b[^|;&]*\$\{?\w*(ANTHROPIC|TELEGRAM|API_KEY|TOKEN|SECRET|PASSWORD|KIS_|TOSS_)\w*"
)
GIT_FORCE = re.compile(r"\bgit\s+push\b.*(\s--force(-with-lease)?\b|\s-f\b|\s\+\S)")
GIT_ADD_ALL = re.compile(r"\bgit\s+add\s+(-A\b|--all\b|\.(\s|$)|\*\s*$|-u\b)")
GIT_COMMIT_ALL = re.compile(r"\bgit\s+commit\b.*\s(-a|--all|-am)\b")
GIT_REVERT_OTHERS = re.compile(
    r"\bgit\s+(checkout\s+(--|\.)|restore\b|stash\b|reset\s+--hard|clean\b|branch\s+-D)"
)
GIT_PUSH = re.compile(r"\bgit\s+push\b")
RAW_WRITE = re.compile(
    r"((>|>>)\s*\S*data/raw|\b(tee|mv|cp|rm|truncate|gzip|gunzip|unlink|shred|install)\b[^|;&]*data/raw|sed\s+-i[^|;&]*data/raw)"
)
RM_RECURSIVE = re.compile(r"\brm\s+(-\w*[rR]\w*|--recursive)")
RM_DANGEROUS_TARGET = re.compile(
    r"(data/|private/|reports/|digests/|vault/|seed/|\.git\b|\s/\s*($|[;&|])|~|\$HOME|\.\./)"
)
PRIVILEGED = re.compile(
    r"(^|[\s;&|(])(sudo|pmset|crontab\s+-[er])\b|launchctl\s+(bootstrap|bootout|load|unload|kickstart|remove)\b"
)
FACTCHECK_WRITE = re.compile(
    r"(>|>>|\btee\b|\bmv\b|\bcp\b|\brm\b|\bsed\s+-i|\btouch\b|\bmkdir\b|\bgit\s+(add|commit|push|checkout|restore)\b|uv\s+run\s+macroweb\s+(quality\s+apply|graph\s+(add|merge|apply)|db\s+(init|migrate)|phase\s+set))"
)
HEREDOC_START = re.compile(r"(?:^|(?<=\s))<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|(\w+))")


def strip_heredocs(cmd):
    """Drop heredoc bodies but keep the command lines themselves (redirect targets stay visible)."""
    lines = cmd.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEREDOC_START.search(line)
        out.append(line)
        i += 1
        if m:
            delim = m.group(1) or m.group(2) or m.group(3)
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1  # skip the terminator line
    return "\n".join(out)


def decide(decision, reason, payload, cmd):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    _log(payload, cmd, decision, reason)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def _log(payload, cmd, decision, reason):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        os.makedirs(os.path.join(root, "logs"), exist_ok=True)
        with open(os.path.join(root, "logs", "hooks.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": int(time.time()),
                        "hook": "guard_bash",
                        "agent": payload.get("agent_type"),
                        "decision": decision,
                        "reason": reason,
                        "cmd": cmd[:300],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except OSError:
        pass


def evaluate(raw_cmd, agent_type=None):
    """Returns (decision, reason) or None to allow. Pure function so tests can call it directly."""
    cmd = strip_heredocs(raw_cmd)
    if SECRET_PATH.search(cmd) and (
        READER.search(cmd) or DOT_SOURCE.search(cmd) or INPUT_REDIRECT.search(cmd)
    ):
        return (
            "deny",
            "비밀값 파일(private/, .env*, 토큰 파일)은 읽지도 출력하지도 않는다 (CLAUDE.md 불변 규칙 7). 변수 이름은 private/env.example 을 본다.",
        )
    if ENV_DUMP.search(cmd) or ECHO_SECRET.search(cmd):
        return (
            "deny",
            "환경변수 덤프/비밀값 echo 금지 — 키가 세션 기록에 남는다. 존재 여부만 필요하면 `uv run macroweb doctor --quick` 을 쓴다.",
        )
    if GIT_FORCE.search(cmd):
        return ("deny", "git push --force 금지 (CLAUDE.md 불변 규칙 8).")
    if GIT_ADD_ALL.search(cmd) or GIT_COMMIT_ALL.search(cmd):
        return (
            "deny",
            "git add -A/--all/. 와 commit -a 금지 — 자기 변경만 파일 단위로 add 한다 (다른 세션의 변경이 섞인다).",
        )
    if RAW_WRITE.search(cmd):
        return ("deny", "data/raw 스냅샷은 수정·삭제 금지 (PLAN §2-1, 데이터 규칙). 보존 정책 변경은 ADR 로.")
    if agent_type == "fact-checker" and FACTCHECK_WRITE.search(cmd):
        return (
            "deny",
            "fact-checker 는 읽기 전용이다 — 검수자가 수정하면 검수가 아니다 (PLAN §10.1). PASS/FAIL 과 위반 목록만 출력한다.",
        )
    if RM_RECURSIVE.search(cmd):
        if RM_DANGEROUS_TARGET.search(cmd):
            return (
                "deny",
                "rm -r 대상이 data/·private/·reports/·digests/·vault/·seed/·.git·홈/루트다. 삭제는 매니페스트+사용자 승인 후에만.",
            )
        return ("ask", "rm -r: 대상을 확인한다 (캐시·임시 디렉터리만 허용).")
    if GIT_REVERT_OTHERS.search(cmd):
        return (
            "ask",
            "자기가 만들지 않은 미커밋 변경을 되돌릴 수 있는 명령이다. 이 세션이 만든 변경일 때만 진행.",
        )
    if GIT_PUSH.search(cmd):
        return (
            "ask",
            "원격(github.com/sawoo9410/macroWeb)으로 발행된다. 커밋 내용에 private/·data/ 가 없는지 확인 후 진행.",
        )
    if PRIVILEGED.search(cmd):
        return ("ask", "시스템 상태를 바꾸는 명령(sudo/launchctl/pmset/crontab). 근거를 확인하고 진행.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    verdict = evaluate(cmd, payload.get("agent_type"))
    if verdict is None:
        sys.exit(0)
    decide(verdict[0], verdict[1], payload, cmd)


if __name__ == "__main__":
    main()
