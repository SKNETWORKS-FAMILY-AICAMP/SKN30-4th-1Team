"""History topic tokenization tests independent of any evaluation examples."""

import ast
import os
import subprocess
import sys
from pathlib import Path

from backend.retriever import history_intent


_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_module_contains_no_regex_or_phrase_classifier():
    source = Path(history_intent.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_names = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    classifier_tables = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(
            node.value,
            (ast.List, ast.Tuple, ast.Set, ast.Dict),
        )
    ]

    assert "re" not in imported_modules
    assert "re" not in imported_names
    assert classifier_tables == []


def test_topic_tokens_share_one_canonical_space():
    question_tokens = history_intent.extract_content_tokens(
        "Nimbus42 모듈 상태"
    )
    component_tokens = history_intent.content_tokens("Nimbus42 모듈")

    assert question_tokens & component_tokens == {"nimbus", "42", "모듈"}


def test_noun_only_topic_extraction_has_script_neutral_fallback():
    assert history_intent.extract_content_tokens("었어?") == {"었어"}
    assert history_intent.content_tokens("") == set()
    assert history_intent.content_tokens("   ") == set()


def test_unicode_fallback_normalizes_nfkc_and_supports_multiple_scripts(
    monkeypatch,
):
    monkeypatch.setattr(history_intent, "_kiwi", False)

    assert history_intent.extract_content_tokens(
        "Ａｌｐｈａ العربية 東京"
    ) == {"alpha", "العربية", "東京"}


def test_east_asian_unsegmented_text_has_generic_local_overlap():
    chinese_topic = history_intent.extract_content_tokens("支付模块")
    chinese_sentence = history_intent.content_tokens("支付模块怎么了")
    japanese_topic = history_intent.extract_content_tokens("決済モジュール")
    japanese_sentence = history_intent.content_tokens("決済モジュールはどうなった")

    assert {"支付", "模块"} <= chinese_topic & chinese_sentence
    assert japanese_topic & japanese_sentence


def test_tokenization_is_not_limited_to_a_fixed_language_phrase_list():
    assert history_intent.extract_content_tokens(
        "Quartz17 deployment module"
    ) == {"quartz", "17", "deployment", "module"}


def test_module_imports_standalone():
    modules = [
        "backend.retriever.history_intent",
        "backend.retriever.qa_engine",
        "backend.project_memory",
        "backend.api.query",
    ]
    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            env={**os.environ, "PAIM_AUTH_MODE": "dev"},
        )
        assert result.returncode == 0, result.stderr
