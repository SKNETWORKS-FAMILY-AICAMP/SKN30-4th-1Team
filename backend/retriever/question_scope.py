"""Structured, request-stable interpretation of a project Q&A question."""

from __future__ import annotations

import json
import unicodedata
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryCategory = Literal["decision", "action", "issue", "risk"]
CompletionStatus = Literal["open", "completed", "unknown"]


class QuestionScope(BaseModel):
    """Only constraints explicitly requested by the user.

    ``None`` means that the question did not state the constraint.  The scope
    is produced once per request and is injected into every Tool call so one
    model turn cannot silently widen or reverse a later database query.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    operation: Optional[Literal["list", "count", "overview"]] = None
    category: Optional[MemoryCategory] = None
    categories: list[MemoryCategory] = Field(default_factory=list)
    owner: Optional[str] = None
    owners: list[str] = Field(default_factory=list)
    excluded_owners: list[str] = Field(default_factory=list)
    completion_status: Optional[CompletionStatus] = None
    completion_statuses: list[CompletionStatus] = Field(default_factory=list)
    due_within_days: Optional[int] = Field(default=None, ge=0, le=365)
    overdue: bool = False
    subject: Optional[str] = None
    include_history: bool = False
    inherit_previous_topic: bool = False
    history_scope: Optional[Literal["topical", "global"]] = None
    history_topic: Optional[str] = None

    @field_validator("owner", "subject", "history_topic", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("text constraints must be strings")
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized:
            raise ValueError("text constraints cannot be empty")
        return normalized

    @field_validator("owners", "excluded_owners", mode="before")
    @classmethod
    def normalize_owner_lists(cls, value):
        if not isinstance(value, list):
            raise ValueError("owner constraints must be lists")
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("owner constraints must contain only strings")
            normalized = unicodedata.normalize("NFKC", item).strip()
            if not normalized:
                raise ValueError("owner constraints cannot contain empty text")
            key = normalized.casefold()
            if key in seen:
                raise ValueError("owner constraints cannot contain duplicates")
            seen.add(key)
            result.append(normalized)
        return result

    @field_validator("categories", "completion_statuses", mode="before")
    @classmethod
    def require_explicit_lists(cls, value):
        if not isinstance(value, list):
            raise ValueError("multi-value constraints must be lists")
        if len(value) != len(set(value)):
            raise ValueError("multi-value constraints cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_combinations(self):
        if self.category is not None and self.categories:
            raise ValueError("use either category or categories")
        if self.owner is not None and self.owners:
            raise ValueError("use either owner or owners")
        if self.completion_status is not None and self.completion_statuses:
            raise ValueError(
                "use either completion_status or completion_statuses"
            )
        if self.inherit_previous_topic and not self.include_history:
            raise ValueError("inherit_previous_topic requires include_history")
        if self.include_history and self.history_scope is None:
            raise ValueError("include_history requires history_scope")
        if not self.include_history and (
            self.history_scope is not None or self.history_topic is not None
        ):
            raise ValueError("history scope requires include_history")
        if self.history_scope == "topical" and self.history_topic is None:
            raise ValueError("topical history requires history_topic")
        if self.history_scope == "global" and self.history_topic is not None:
            raise ValueError("global history cannot have history_topic")
        if self.overdue and self.due_within_days is not None:
            raise ValueError("overdue conflicts with due_within_days")
        if self.overdue and self.completion_status not in (None, "open"):
            raise ValueError("overdue is only compatible with open actions")
        if self.overdue and self.completion_statuses not in ([], ["open"]):
            raise ValueError("overdue is only compatible with open actions")
        category_values = (
            [self.category] if self.category is not None else self.categories
        )
        if (
            self.completion_status is not None
            or self.completion_statuses
            or self.due_within_days is not None
            or self.overdue
        ) and category_values != ["action"]:
            raise ValueError("status and due constraints require action category")
        if self.operation == "overview" and (
            self.category is not None
            or self.categories
            or self.owner is not None
            or self.owners
            or self.excluded_owners
            or self.completion_status is not None
            or self.completion_statuses
            or self.due_within_days is not None
            or self.overdue
            or self.subject is not None
        ):
            raise ValueError("overview cannot include row filters")
        included_owners = (
            [self.owner] if self.owner is not None else self.owners
        )
        excluded = {value.casefold() for value in self.excluded_owners}
        if any(value.casefold() in excluded for value in included_owners):
            raise ValueError("owner cannot also be excluded")
        return self


_SCOPE_SYSTEM_PROMPT = """\
Read the user turns and return only constraints explicitly requested by the
latest user question. Earlier user turns may be used only when the latest turn
clearly refers back to them. Never use assistant statements as facts.

Use operation for the requested result shape. Use the singular category,
owner, or completion_status field only when exactly one value is requested.
Use categories, owners, or completion_statuses when the user requests multiple
values, preserving every requested value. Use excluded_owners for every
explicitly excluded owner. Put a named task, component, artifact, or other
natural-language target in subject instead of discarding it. Status and date
fields apply only when stated. include_history means superseded or earlier
project states are needed. history_scope is global only when the user asks
across all project history; otherwise it is topical and history_topic contains
only the subject. inherit_previous_topic means the latest question cannot
identify its subject without the preceding user turn.

Do not guess missing values. Leave them null, false, or empty.
"""


def resolve_question_scope(
    question: str,
    user_history: list[str] | None = None,
    *,
    model,
) -> QuestionScope:
    """Resolve one immutable scope with a structured-output capable model."""
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    normalized_question = unicodedata.normalize("NFKC", question).strip()
    if not normalized_question:
        raise ValueError("question cannot be empty")
    if user_history is not None and not isinstance(user_history, list):
        raise TypeError("user_history must be a list")
    turns = []
    for value in (user_history or [])[-3:]:
        if not isinstance(value, str):
            raise TypeError("user_history must contain only strings")
        normalized = unicodedata.normalize("NFKC", value).strip()
        if normalized:
            turns.append(normalized)
    payload = {
        "previous_user_turns": turns,
        "latest_user_question": normalized_question,
    }
    scoped_model = model.with_structured_output(QuestionScope)
    result = scoped_model.invoke([
        SystemMessage(content=_SCOPE_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ])
    if isinstance(result, QuestionScope):
        return result
    return QuestionScope.model_validate(result)
