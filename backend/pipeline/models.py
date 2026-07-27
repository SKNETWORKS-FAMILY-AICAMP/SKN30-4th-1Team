from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    category: Literal["decision", "action", "issue", "risk"]
    content: str = Field(description="Full description of the decision/action/issue/risk")
    reason: Optional[str] = Field(default=None, description="Only for decision: why this was decided")
    topic: Optional[str] = Field(default=None, description="Short keyword theme, e.g. '기술스택', '일정', 'UI설계'")
    owner: Optional[str] = Field(default=None, description="Person responsible or who mentioned it")
    date: Optional[str] = Field(default=None, description="Meeting or document date in YYYY-MM-DD format only")
    source: Optional[str] = Field(default=None, description="Document filename or source identifier")
    completed: Optional[bool] = Field(
        default=None,
        description=(
            "For actions: true only when the text explicitly reports the work is already done; "
            "false when it is explicitly assigned, pending, or in progress; null when status is unclear"
        ),
    )


class CompletionReport(BaseModel):
    action_id: int = Field(description="id of an existing open action from the provided list — never invent one")
    evidence: str = Field(description="The literal sentence from the input text reporting this action's status")
    fully_complete: bool = Field(
        description="True only when the text confirms every sub-task of this action is done. "
        "False when the text confirms only part of it is done while another part remains — "
        "in that case fill done_parts and remaining_parts instead of marking it fully complete."
    )
    # 묶음 action은 sub-task가 2개보다 많을 수 있어 리스트로 받는다. 2개짜리(1완료/1잔여)는
    # 각 리스트 원소 1개인 특수 경우로 그대로 표현된다.
    done_parts: List[str] = Field(
        default_factory=list,
        description="Only when fully_complete is false: every sub-task the text confirms is done, one per entry, in the action's own words",
    )
    remaining_parts: List[str] = Field(
        default_factory=list,
        description="Only when fully_complete is false: every sub-task that is still open, one per entry, in the action's own words",
    )


class ExtractionResult(BaseModel):
    items: List[MemoryItem]
    completions: List[CompletionReport] = Field(default_factory=list)
