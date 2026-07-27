# 문서 텍스트에서 결정/액션/이슈/리스크를 LLM으로 추출하는 모듈.
# 대용량 문서는 문단 경계 기반 청크로 분할해 각각 추출한 뒤 합산하고 중복을 제거한다.
import re
from typing import Callable, List, Optional, Set, Tuple, Union
from .models import MemoryItem, ExtractionResult, CompletionReport
from ..llm import get_llm_client, Message


class PartialExtractionError(Exception):
    """멀티청크 추출 중 일부 청크만 실패했을 때 raise. 부분 결과(items)를 속성으로 포함."""
    def __init__(self, items: List[MemoryItem], failed: int, total: int):
        self.items = items
        self.failed = failed
        self.total = total
        super().__init__(f"{failed}/{total} chunks failed — partial results available")

# LLM에게 전달하는 추출 지침.
# 날짜는 반드시 YYYY-MM-DD 형식, 마감일은 content에 포함시키도록 명시.
SYSTEM_PROMPT = """Extract project decision-related information from the input text.
Rules:
- Extract one object per decision/action/issue/risk.
- Do not extract unclear or ambiguous information.
- Keep extracted content in the same language as the input.
- For action owner, use the assigned person or the person who says
  "~하겠습니다", "~진행하겠습니다", "~공유드리겠습니다", "~정리하겠습니다".
- For decision, owner is the proposer or speaker.
- For issue, owner is the person who raised it.
- For risk, owner is the person who mentioned it.
[Category Definitions & Examples]
- decision: Formally agreed or concluded matters. (e.g., "기술 스택을 FastAPI로 결정함")
- action: Tasks assigned to a specific person with clear next steps. (e.g., "홍길동님이 API 명세서를 작성하겠습니다")
- issue: Current problems that have already occurred and need immediate attention. (e.g., "MySQL 연결 테스트 중 타임아웃 발생")
- risk: Potential future threats, uncertainties, or schedule bottlenecks. (e.g., "다음 달 백엔드 인력 부족으로 일정 지연 우려")
- Do not infer unstated reasons.
- reason field is only for decision category, leave null otherwise.
- topic field: short keyword theme (2-5 words) summarizing what the item is about, e.g. "기술스택 선정", "일정 리스크", "UI 설계". Always fill this in.
- date field must always be the meeting or document date, not a deadline. Format: YYYY-MM-DD (e.g. 2026-06-02). Never use Korean format like "2026년 6월 2일".
- For action items, completed is true only for an explicit report that the work is already done,
  false for assigned/pending/in-progress work, and null only when the status is unclear.
  Judge this from tense and context, not from the word "complete" alone.
- For action items, if a deadline is mentioned, append it to content (e.g. "문서 초안 작성 (~6/22까지)"). Do not put the deadline in the date field."""

_REPO_PROMPTS = {
    "repo_readme": """

Source-specific rules for repository README:
- These source-specific rules override the general extraction examples below.
- This source is a README, not a meeting note.
- Do not extract installation steps, usage instructions, setup commands, CLI examples, or prerequisites as action items.
- Do not extract actions from sections such as Install, Usage, Quick start, Getting started, Environment, Docker, Build, Run, 실행, 설치, 개발 환경, or 사용법.
- Extract project purpose, architecture, technology decisions, explicit limitations, known issues, and risks.
- Extract action items only from explicit Roadmap/TODO/Next steps sections and only when the item is clearly unfinished.
- Before returning an action item, verify that it comes from an explicit roadmap/TODO/next-step section. Otherwise omit it.
""",
    "repo_commits": """

Source-specific rules for repository commits:
- These source-specific rules override the general extraction examples below.
- Commits are records of work that already happened.
- If extracting a commit as an action, the action is already completed and completed must be true.
- Use the commit date as the date field when present.
- Extract valuable decisions such as migrations, architecture changes, or technology choices.
- Do not create unfinished action items from past-tense commit messages.
""",
    "repo_issues": """

Source-specific rules for open repository issues:
- Open issues mainly represent current issues, risks, or unresolved work.
- Existing action extraction is acceptable when the issue body clearly assigns next steps.
- Do not mark open issue actions as completed unless the text explicitly says they are already done.
""",
    "repo_prs": """

Source-specific rules for open repository pull requests:
- Open PRs represent in-progress work.
- Extract concrete pending review/merge/follow-up work as action items.
- Do not mark open PR actions as completed unless the text explicitly says a subtask is already done.
- Extract decisions when the PR states a clear implementation or architecture choice.
""",
}

_CHUNK_SIZE = 15000  # 청크당 최대 문자 수
_CHUNK_OVERLAP = 200  # 청크 경계에서 문맥 유지를 위해 앞 청크와 겹치는 문자 수


def _system_prompt(source_kind: str) -> str:
    """기본 회의록 프롬프트는 유지하고 repo 소스에만 우선 지침을 더한다."""
    return _REPO_PROMPTS.get(source_kind, "") + SYSTEM_PROMPT


# 열린 action 목록을 system prompt에 넣을 때의 상한. 이 system은 청크마다 재사용되므로
# (_CHUNK_SIZE=15000자) 목록이 커지면 매 청크에서 컨텍스트를 잡아먹어 결국 그 프로젝트의
# 문서 업로드가 통째로 extraction 실패로 끝난다. action content는 API로 생성 가능해
# 개수·길이 모두 상한이 없으므로 세 축을 각각 막는다.
_OPEN_ACTIONS_MAX_ITEMS = 50      # 항목 수
_OPEN_ACTIONS_MAX_CHARS = 4000    # 렌더링된 목록 전체 문자 수
_OPEN_ACTIONS_ITEM_CHARS = 200    # 항목 하나가 예산을 독식하지 않도록 개별 절단


def cap_open_actions(open_actions: List[dict]) -> List[dict]:
    """프롬프트에 넣을 열린 action 목록을 예산 안으로 자른다.

    최신순(_fetch_open_actions가 created_at DESC)이므로 앞에서부터 채우고, 예산을 넘기면
    거기서 끊는다. 잘린 항목은 이 문서에서 완료 판정 대상이 되지 않는다 — 목록 전체를
    넣어 extraction 자체를 실패시키는 것보다 일부만 판정하는 쪽이 낫다는 판단.
    호출부가 이 결과를 extract()와 ingest()에 **같이** 넘겨야 한다. 그러지 않으면 LLM이
    본 적 없는 id가 ingest의 허용 목록을 통과한다.
    """
    capped, used = [], 0
    for a in open_actions[:_OPEN_ACTIONS_MAX_ITEMS]:
        content = (a.get("content") or "")[:_OPEN_ACTIONS_ITEM_CHARS]
        used += len(content) + len(str(a.get("id", ""))) + 20  # id/담당/서식 오버헤드 개산
        if used > _OPEN_ACTIONS_MAX_CHARS:
            break
        capped.append({**a, "content": content})
    return capped


def _open_actions_prompt(open_actions: List[dict]) -> str:
    """현재 열린 action 목록을 프롬프트에 덧붙여, 이 문서가 그중 일부를 완료로
    보고하는지 같은 추출 호출 안에서 함께 판정하게 한다(사후 reconciler 대체).
    """
    lines = "\n".join(
        f"- id={a['id']}: {a['content']}" + (f" (담당: {a['owner']})" if a.get("owner") else "")
        for a in open_actions
    )
    return f"""

Additionally, here is the list of currently open (not yet completed) action items from
earlier meetings, each with its id:
{lines}

If this document reports progress on one or more of these exact items (e.g. in a
"지난 액션 이행 확인" or progress-report section), return them in `completions` with the
literal sentence as evidence.
- Only use action_id values from the list above — never invent one.
- One sentence can report progress on multiple items at once.
- Skip an item entirely (do not include it in `completions`) when the text gives no
  concrete progress on it, or only says it is planned/not started.
- Set fully_complete=true only when the text explicitly states the entire item is
  already done. Do not set it true for in-progress, partially done work, or a bare
  percentage (e.g. "80% 진행됐습니다").
- If an item bundles multiple sub-tasks (e.g. "X 기능 및 Y 로직 구현") and the text
  confirms only some of them done while another part remains in-progress or unmentioned,
  do NOT set fully_complete=true. Instead set fully_complete=false and fill done_part
  (the confirmed-done sub-task, in the action's own words) and remaining_part (the
  sub-task that is not yet confirmed done, in the action's own words) — this splits the
  item so the finished part is recorded without prematurely closing the rest.
  The text may name a sub-task with different wording than the item's own text (e.g.
  item says "알림 로직 구현", text says "알림은 푸시 연동 중입니다" — that is the same
  sub-task, still open).
- If nothing on the list has any reportable progress, return an empty completions array."""


_README_ACTION_BLOCKLIST = (
    ".env",
    "api 키",
    "build",
    "db 비밀번호",
    "docker",
    "environment",
    "getting started",
    "install",
    "mysql",
    "node.js",
    "prerequisite",
    "quick start",
    "requirements",
    "run",
    "rust",
    "setup",
    "usage",
    "cargo",
    "xcode",
    "webview2",
    "빌드",
    "사용법",
    "설치",
    "실행",
    "의존성",
    "환경변수",
    "개발 환경",
)


def _post_process_items(items: List[MemoryItem], source_kind: str) -> List[MemoryItem]:
    """repo 소스에서 LLM이 지침을 어긴 대표 케이스를 결정적으로 정리한다."""
    if source_kind == "repo_commits":
        for item in items:
            if item.category == "action":
                item.completed = True
        return items

    if source_kind != "repo_readme":
        return items

    filtered = []
    for item in items:
        if item.category != "action":
            filtered.append(item)
            continue
        content = item.content.lower()
        if any(term in content for term in _README_ACTION_BLOCKLIST):
            continue
        filtered.append(item)
    return filtered


def _slice_chunks(text: str, chunk_size: int) -> List[str]:
    """단일 초대형 문단은 기존 글자 수 슬라이스 방식으로 나눈다."""
    if len(text) <= chunk_size:
        return [text]
    overlap = min(_CHUNK_OVERLAP, chunk_size - 1)
    step = chunk_size - overlap
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks


def _split_chunks(text: str, chunk_size: Optional[int] = None) -> List[str]:
    """텍스트를 문단 경계 기준으로 분할. 짧으면 그대로 반환."""
    chunk_size = _CHUNK_SIZE if chunk_size is None else chunk_size
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    current: List[str] = []
    current_len = 0
    paragraphs = text.split("\n\n")

    for idx, paragraph in enumerate(paragraphs):
        unit = paragraph + ("\n\n" if idx < len(paragraphs) - 1 else "")

        if len(paragraph) > chunk_size or len(unit) > chunk_size:
            if current:
                chunks.append("".join(current))
                current = []
                current_len = 0
            chunks.extend(_slice_chunks(unit, chunk_size))
            continue

        if current and current_len + len(unit) > chunk_size:
            chunks.append("".join(current))
            current = []
            current_len = 0

        current.append(unit)
        current_len += len(unit)

    if current:
        chunks.append("".join(current))
    return chunks


def _notify_progress(on_progress: Optional[Callable[[int, int], None]], done: int, total: int) -> None:
    if not on_progress:
        return
    try:
        on_progress(done, total)
    except Exception:
        pass


def _extract_chunk(
    client, text: str, default_source: str, source_kind: str,
    open_actions: Optional[List[dict]] = None,
) -> Tuple[List[MemoryItem], List[CompletionReport]]:
    """단일 청크를 LLM function calling으로 구조화 추출.
    tool_input=None → LLM이 tool call 자체를 안 한 것(실패), ValueError raise.
    items=[] → 추출할 내용 없음(정상 빈 결과).
    open_actions가 있으면 같은 호출에서 그중 완료 보고된 항목도 함께 판정한다.
    """
    system = _system_prompt(source_kind)
    if open_actions:
        system += _open_actions_prompt(open_actions)
    response = client.chat(
        messages=[Message(role="user", content=f"Input:\n{text}")],
        system=system,
        tool_schema=ExtractionResult.model_json_schema(),
        tool_name="extract_memory",
    )
    # tool_input이 None이면 LLM이 tool call 자체를 안 한 것 (진짜 실패)
    # items가 빈 리스트면 추출할 내용이 없는 것 (정상)
    if response.tool_input is None:
        raise ValueError("LLM did not return tool output for chunk")
    result = ExtractionResult(**response.tool_input)
    items = result.items
    for item in items:
        if not item.source:
            item.source = default_source  # LLM이 source 미반환 시 파일명으로 fallback
    return _post_process_items(items, source_kind), result.completions


def _dedup_completions(completions: List[CompletionReport]) -> List[CompletionReport]:
    """같은 action_id가 여러 청크에서 보고되면 마지막 보고만 남긴다(청크 순서 = 문서 내
    등장 순서). 앞부분 요약이 "전체 완료"라고 뭉뚱그려도, 뒷부분 구체 섹션이 "일부만
    완료"라고 더 정확히 정정하면 그게 이겨야 한다 — fully_complete를 무조건 우선하면
    이른 시점의 부정확한 낙관적 보고가 나중의 더 정확한 부분완료 보고를 덮어써버린다.
    """
    best: dict[int, CompletionReport] = {}
    for c in completions:
        best[c.action_id] = c
    return list(best.values())


def _norm_date_key(date_str: str) -> str:
    """중복 제거 키 생성용 날짜 정규화. '2026년 6월 2일' → '2026-06-02'."""
    if not date_str:
        return ""
    m = re.match(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r'(\d{4})[./](\d{1,2})[./](\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return date_str.strip()


def _dedup(items: List[MemoryItem]) -> List[MemoryItem]:
    """청크 경계 오버랩으로 생긴 중복 항목 제거.
    (category, content, 정규화된 date, source) 4개 키 기준으로 판단.
    날짜가 같아도 date 표현이 다른 경우를 위해 _norm_date_key 적용.
    """
    seen: Set[Tuple] = set()
    result = []
    for item in items:
        key = (
            item.category,
            item.content.strip().lower(),
            _norm_date_key(item.date or ""),
            (item.source or "").strip().lower(),
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def extract(
    text: str,
    provider: str = None,
    default_source: str = "",
    source_kind: str = "document",
    on_progress: Optional[Callable[[int, int], None]] = None,
    open_actions: Optional[List[dict]] = None,
) -> Union[List[MemoryItem], Tuple[List[MemoryItem], List[CompletionReport]]]:
    """메인 추출 함수.
    1. 텍스트를 청크로 분할
    2. 청크별 LLM 추출 (_extract_chunk)
    3. 결과 합산 후 중복 제거 (_dedup)
    일부 청크 실패 시 PartialExtractionError(부분 결과 포함) raise.
    전체 실패 시 ValueError raise.

    open_actions를 넘기면 이 문서가 그 목록 중 일부를 완료로 보고하는지 같은 LLM
    호출에서 함께 판정하고(사후 reconciler 대체), 반환값이 (items, completions)
    튜플이 된다. 넘기지 않으면 기존과 동일하게 items 리스트만 반환한다(하위 호환).
    """
    client = get_llm_client(provider)
    chunks = _split_chunks(text)
    total_chunks = len(chunks)
    _notify_progress(on_progress, 0, total_chunks)

    all_items: List[MemoryItem] = []
    all_completions: List[CompletionReport] = []
    failed_chunks = 0
    for idx, chunk in enumerate(chunks, start=1):
        try:
            items, completions = _extract_chunk(
                client, chunk, default_source, source_kind, open_actions
            )
            all_items.extend(items)
            all_completions.extend(completions)
        except ValueError:
            failed_chunks += 1  # 청크 실패 카운트, 나머지 청크는 계속 처리
        finally:
            _notify_progress(on_progress, idx, total_chunks)

    if failed_chunks == len(chunks):
        raise ValueError("LLM did not return structured output for any chunk")

    deduped = _dedup(all_items)

    if failed_chunks > 0:
        raise PartialExtractionError(deduped, failed_chunks, len(chunks))

    if open_actions is not None:
        return deduped, _dedup_completions(all_completions)
    return deduped
