from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    category: Literal["decision", "action", "issue", "risk"]
    content: str = Field(description="Full description of the decision/action/issue/risk")
    reason: Optional[str] = Field(default=None, description="Only for decision: why this was decided")
    topic: Optional[str] = Field(default=None, description="Short keyword theme, e.g. '기술스택', '일정', 'UI설계'")
    owner: Optional[str] = Field(default=None, description="Person responsible or who mentioned it")
    date: Optional[str] = Field(default=None, description="Meeting or document date in YYYY-MM-DD format only")
    due_date: Optional[str] = Field(
        default=None,
        description=(
            "For actions only: normalized deadline candidate in YYYY-MM-DD. "
            "Null when no single calendar date can be determined"
        ),
    )
    due_date_text: Optional[str] = Field(
        default=None,
        description="Exact deadline phrase copied from the input, for provenance and review",
    )
    due_date_requires_confirmation: bool = Field(
        default=False,
        description=(
            "True when due_date was resolved from a relative or year-omitted phrase and must "
            "be approved before it is stored"
        ),
    )
    source: Optional[str] = Field(default=None, description="Document filename or source identifier")
    completed: Optional[bool] = Field(
        default=None,
        description=(
            "For actions: true only when the text explicitly reports the work is already done; "
            "false when it is explicitly assigned, pending, or in progress; null when status is unclear"
        ),
    )


class ExtractionResult(BaseModel):
    items: List[MemoryItem]
