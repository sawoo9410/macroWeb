"""Prompt assembly: versioned prompt files (`prompts/<name>/v<N>.md`, frontmatter + body) become the cached
system block; the Story metadata + body become the user message. Pure, so Phase 2 tests can pin the exact
text that reaches the model (§6.3: every run records its prompt versions)."""

from __future__ import annotations

from dataclasses import dataclass

from macroweb.extract.contracts import StoryInput
from macroweb.paths import PROMPTS_DIR

CHARS_PER_TOKEN = 3.2  # conservative for mixed Korean/English; Phase 2 replaces with count_tokens


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: int
    system: str
    meta: dict[str, str]

    @property
    def version_tag(self) -> str:
        return f"{self.name}@v{self.version}"


def load_prompt(name: str, version: int) -> PromptSpec:
    path = PROMPTS_DIR / name / f"v{version}.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} lacks frontmatter")
    _, header, body = text.split("---", 2)
    meta: dict[str, str] = {}
    for line in header.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    if int(meta.get("version", "0")) != version:
        raise ValueError(f"{path}: frontmatter version {meta.get('version')} != {version}")
    return PromptSpec(name=name, version=version, system=body.strip(), meta=meta)


def truncate_body(text: str, max_tokens: int) -> tuple[str, bool]:
    """Keep the head (lead paragraphs carry the facts) and a short tail; mark truncation explicitly."""
    limit = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text, False
    head = text[: int(limit * 0.85)]
    tail = text[-int(limit * 0.10) :]
    return f"{head}\n\n[… 중략: 본문 {len(text):,}자 중 일부 생략 …]\n\n{tail}", True


def build_extraction_messages(story: StoryInput, spec: PromptSpec, max_input_tokens: int) -> tuple[str, str]:
    """(system, user). System = prompt body (identical across stories → prompt-cache hit); user = meta + body."""
    body, truncated = truncate_body(story.text or story.title, max_input_tokens)
    meta_lines = [
        f"source_id: {story.source_id}",
        f"tier: T{story.tier}",
        f"stratum: {story.stratum}",
        f"published_at: {story.published_at or 'unknown'}",
        f"lang: {story.lang}",
        f"url: {story.url}",
        f"independent_sources: {story.n_independent}",
        f"truncated: {'yes' if truncated else 'no'}",
    ]
    user = "## 메타\n" + "\n".join(meta_lines) + f"\n\n## 제목\n{story.title}\n\n## 본문\n{body}"
    return spec.system, user
