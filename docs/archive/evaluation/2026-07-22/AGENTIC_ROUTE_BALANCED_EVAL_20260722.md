# PaiM Route-Balanced Golden Set 평가 보고서

- 데이터셋: `paim-route-balanced-golden-20260722`
- 원문 기준 커밋: `5240f4047187073725ff8b6dfaeedf5e9a6d8af7`
- 골든 문항: 40개 · 실제 결과: 40개
- API 성공: 40/40
- 도구 선택: 37/40 (92.5%)
- 도구 인자: 35/40 (87.5%)
- 도구 라운드: 40/40 (100.0%)
- 어휘·계약 신호: 20/40 (50.0%)
- 결정론 신호 종합: 16/40 (40.0%)
- 최종 답변 판정: 일치 33 · 부분일치 6 · 불일치 1 (판정 40/40)
- 엄격 정답률(PASS): 33/40 (82.5%)
- 핵심 답 포함률(PASS+PARTIAL): 39/40 (97.5%)
- semantic 검색 인자: 11/12 (91.7%)

`—`는 해당 점수가 결과 JSONL에 없어서 집계하지 않았다는 뜻입니다. 도구 인자는 런타임 기본값(limit=8)을 반영한 유효값 기준입니다. `strict_text_pass`는 문자열 포함 여부를 보는 어휘적 프록시이며 의미적 정답률이 아닙니다.

## 핵심 판정

- 자동 Judge는 일치 31 · 부분일치 8 · 불일치 1였고, 동결 스냅샷·원문으로 9건을 재검토한 최종 판정은 33/6/1입니다.
- 기대 도구 집합 불일치: M-MX03, M-MX04, C-OV04
- 유효 도구 인자 불일치: M-MX03, M-MX04, C-OV04, C-MX03, C-MX04
- 답변 부분일치/불일치: M-OV04, M-MX04, C-OV02, C-OV04, C-MX01, C-MX02, C-SE02
- 이 평가셋의 구조화 호출은 24건이지만 category=all 문항은 0건, completion_status 문항은 0건입니다. 따라서 두 계약은 이번 점수로 검증할 수 없습니다.
- 골든셋 동봉 검증기는 978개 검사를 모두 통과했습니다. 다만 '대표 액션'처럼 정답이 여러 개 가능한 질문은 특정 항목 하나를 강제하면 과적합 판정이 생길 수 있어 의미 재검토를 우선했습니다.

### 코퍼스별

| 구분 | 문항 | API 성공 | 도구 선택 | 도구 인자 | 도구 라운드 | 어휘·계약 신호 | 결정론 신호 종합 | Judge 일치/부분/불일치 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| modu | 20 | 20/20 | 18/20 (90.0%) | 18/20 (90.0%) | 20/20 (100.0%) | 13/20 (65.0%) | 11/20 (55.0%) | 18/2/0 |
| csbot | 20 | 20/20 | 19/20 (95.0%) | 17/20 (85.0%) | 20/20 (100.0%) | 7/20 (35.0%) | 5/20 (25.0%) | 15/4/1 |

### 질문 family별

| 구분 | 문항 | API 성공 | 도구 선택 | 도구 인자 | 도구 라운드 | 어휘·계약 신호 | 결정론 신호 종합 | Judge 일치/부분/불일치 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| structured_count | 10 | 10/10 | 10/10 (100.0%) | 10/10 (100.0%) | 10/10 (100.0%) | 9/10 (90.0%) | 9/10 (90.0%) | 10/0/0 |
| structured_list | 10 | 10/10 | 10/10 (100.0%) | 10/10 (100.0%) | 10/10 (100.0%) | 3/10 (30.0%) | 3/10 (30.0%) | 10/0/0 |
| overview | 8 | 8/8 | 7/8 (87.5%) | 7/8 (87.5%) | 8/8 (100.0%) | 1/8 (12.5%) | 1/8 (12.5%) | 5/2/1 |
| mixed_tools | 8 | 8/8 | 6/8 (75.0%) | 4/8 (50.0%) | 8/8 (100.0%) | 5/8 (62.5%) | 1/8 (12.5%) | 5/3/0 |
| semantic_boundary | 4 | 4/4 | 4/4 (100.0%) | 4/4 (100.0%) | 4/4 (100.0%) | 2/4 (50.0%) | 2/4 (50.0%) | 3/1/0 |

## 문항별 비교

### M-SC01 · structured_count · 일치

#### (정답)

**질문**
현재 Modu 프로젝트의 액션 기록은 총 몇 개야?

**답변**

> 동결된 modu 메모리 스냅샷 기준 액션 기록은 총 55건이다.

**참고 문항(출처)**
memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 55,
    "required_terms": [
      "55"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "operation": "count"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
현재 Modu 프로젝트의 액션 기록은 총 몇 개야?

**답변**

> 현재 Modu 프로젝트의 액션 기록은 총 **55개**입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-20_출시전최종개발점검.md, 2026-04-13_모임핵심기능점검_베타준비.md, 2026-04-06_출시일조정_개발중간점검.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "count",
      "text_query": "Modu"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `3023.0 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "55"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "count",
              "text_query": "Modu"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "operation": "count"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 Modu 프로젝트의 액션 기록 총 개수(55개)를 정확히 명시했고, 골든 답변과 의미상 동일하다. 도구 호출에서도 category와 operation이 정확히 맞아 PASS이다.

---

### M-SC02 · structured_count · 일치

#### (정답)

**질문**
정예린이 담당한 액션은 몇 개야?

**답변**

> 동결된 modu 메모리 스냅샷 기준 정예린 담당 액션 기록은 총 8건이다.

**참고 문항(출처)**
memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 8,
    "required_terms": [
      "8"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "operation": "count",
        "owner": "정예린"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
정예린이 담당한 액션은 몇 개야?

**답변**

> 정예린이 담당한 액션은 총 **8개**입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-13_모임핵심기능점검_베타준비.md, 2026-04-06_출시일조정_개발중간점검.md, 2026-03-23_로그인방식재논의_모임기능착수.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "count",
      "owner": "정예린",
      "text_query": "정예린"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2611.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "8"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "count",
              "owner": "정예린",
              "text_query": "정예린"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "operation": "count",
          "owner": "정예린"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 정예린 담당 액션의 개수(8개)를 정확히 명시했고, 골든 답변과 의미상 동일하다. 툴 호출도 owner와 category를 정확히 지정해 의미를 보존했다.

---

### M-SC03 · structured_count · 일치

#### (정답)

**질문**
한지민 담당 리스크는 총 몇 건이야?

**답변**

> 동결된 modu 메모리 스냅샷 기준 한지민 담당 리스크 기록은 총 4건이다.

**참고 문항(출처)**
memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 4,
    "required_terms": [
      "4"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "risk",
        "operation": "count",
        "owner": "한지민"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
한지민 담당 리스크는 총 몇 건이야?

**답변**

> 한지민 담당 리스크는 총 **4건**입니다.

**참고 문항(반환 출처)**
2026-05-11_베타결과리뷰_출시반영사항.md, 2026-03-30_소셜로그인점검_일정리스크평가.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "risk",
      "operation": "count",
      "owner": "한지민",
      "text_query": "한지민"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `1945.6 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "4"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "risk",
              "operation": "count",
              "owner": "한지민",
              "text_query": "한지민"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "risk",
          "operation": "count",
          "owner": "한지민"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 한지민 담당 리스크의 총 건수(4건)를 정확히 답변했고, 의미상 골든 답변과 동일하다. 도구 호출도 owner와 category를 정확히 지정해 PASS다.

---

### M-SC04 · structured_count · 일치

#### (정답)

**질문**
이수진이 담당한 결정은 몇 개야?

**답변**

> 동결된 modu 메모리 스냅샷 기준 이수진 담당 결정 기록은 총 2건이다.

**참고 문항(출처)**
memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 2,
    "required_terms": [
      "2"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "decision",
        "operation": "count",
        "owner": "이수진"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
이수진이 담당한 결정은 몇 개야?

**답변**

> 이수진이 담당한 결정은 **2개**입니다.

**참고 문항(반환 출처)**
2026-03-16_회원시스템점검_관심사확정.md, 2026-03-09_기술스택확정_로그인방식결정.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "decision",
      "operation": "count",
      "owner": "이수진",
      "text_query": "이수진"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2361.6 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "2"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "decision",
              "operation": "count",
              "owner": "이수진",
              "text_query": "이수진"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "decision",
          "operation": "count",
          "owner": "이수진"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 '이수진이 담당한 결정의 개수'를 정확히 2개로 명확하게 답변했다. 골든 답변과 의미상 동일하며, 수치와 담당 관계 모두 정확하다. tool call 역시 요구한 핵심 인자를 모두 포함한다.

---

### M-SC05 · structured_count · 일치

#### (정답)

**질문**
박현우가 담당한 리스크 기록은 몇 건이야?

**답변**

> 동결된 modu 메모리 스냅샷 기준 박현우 담당 리스크 기록은 총 0건이다.

**참고 문항(출처)**
memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 0,
    "required_terms": [
      "0"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "risk",
        "operation": "count",
        "owner": "박현우"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
박현우가 담당한 리스크 기록은 몇 건이야?

**답변**

> 박현우가 담당한 리스크 기록은 **0건**이다.

**참고 문항(반환 출처)**
반환 없음

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "risk",
      "operation": "count",
      "owner": "박현우",
      "text_query": "박현우"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2008.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "0"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "risk",
              "operation": "count",
              "owner": "박현우",
              "text_query": "박현우"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "risk",
          "operation": "count",
          "owner": "박현우"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 박현우 담당 리스크 기록의 개수(0건)를 정확히 답변했고, 골든 답변과 의미상 동일하다. 도구 호출도 owner와 category를 정확히 지정하여 의미를 보존했다.

---

### M-SL01 · structured_list · 일치

#### (정답)

**질문**
정예린이 담당한 액션 목록을 전부 보여줘.

**답변**

> 동결된 스냅샷 기준 정예린 담당 액션 기록은 8건이다.
> - 사용자 플로우 및 와이어프레임 초안 작성
> - 회원가입/로그인 화면 디자인
> - 정예린이 관심사 설정 화면 디자인 확정하겠습니다 (마감 3/20)
> - 모임 탐색/생성 화면 디자인 (마감 3/27)
> - 모임 상세 화면 및 댓글 UI 디자인 (마감 4/10)
> - 베타용 온보딩 튜토리얼 화면 디자인
> - 스토어 등록용 스크린샷 및 소개 이미지 제작 (5/13까지)
> - 1.1 실시간 채팅 UI 디자인 (5/25까지)

**참고 문항(출처)**
sources/modu/2026-03-02_킥오프_앱방향정의.md, sources/modu/2026-03-09_기술스택확정_로그인방식결정.md, sources/modu/2026-03-16_회원시스템점검_관심사확정.md, sources/modu/2026-03-23_로그인방식재논의_모임기능착수.md, sources/modu/2026-04-06_출시일조정_개발중간점검.md, sources/modu/2026-04-13_모임핵심기능점검_베타준비.md, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md, sources/modu/2026-05-15_출시최종점검_1.1로드맵확정.md, memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 8,
    "order_matters": false,
    "required_items": [
      "사용자 플로우 및 와이어프레임 초안 작성",
      "회원가입/로그인 화면 디자인",
      "정예린이 관심사 설정 화면 디자인 확정하겠습니다 (마감 3/20)",
      "모임 탐색/생성 화면 디자인 (마감 3/27)",
      "모임 상세 화면 및 댓글 UI 디자인 (마감 4/10)",
      "베타용 온보딩 튜토리얼 화면 디자인",
      "스토어 등록용 스크린샷 및 소개 이미지 제작 (5/13까지)",
      "1.1 실시간 채팅 UI 디자인 (5/25까지)"
    ],
    "required_owner": "정예린",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "정예린"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
정예린이 담당한 액션 목록을 전부 보여줘.

**답변**

> 정예린이 담당한 액션 목록은 다음과 같습니다.
>
> | 액션명                          | 주제                      | 날짜       | 마감일    | 완료 여부 미확인 |
> |-------------------------------|--------------------------|------------|----------|-----------------|
> | 관심사 설정 화면 디자인 확정    | 관심사 설정 화면 디자인   | 2026-03-16 | 3/20     | 미확인          |
> | 스토어 등록용 스크린샷 및 소개 이미지 제작 | 스토어 등록 이미지         | 2026-05-11 | 5/13     | 미확인          |
> | 회원가입/로그인 화면 디자인     | -                        | 2026-03-09 | -        | 미확인          |
> | 모임 상세 화면 및 댓글 UI 디자인 | UI 디자인                 | 2026-04-06 | 4/10     | 미확인          |
> | 모임 탐색/생성 화면 디자인      | 모임 화면 디자인          | 2026-03-23 | 3/27     | 미확인          |
> | 1.1 실시간 채팅 UI 디자인       | UI 디자인                 | 2026-05-15 | 5/25     | 미확인          |
> | 베타용 온보딩 튜토리얼 화면 디자인 | -                        | 2026-04-13 | -        | 미확인          |
> | 사용자 플로우 및 와이어프레임 초안 작성 | 사용자 플로우 및 와이어프레임 | 2026-03-02 | -        | 미확인          |

**참고 문항(반환 출처)**
2026-03-16_회원시스템점검_관심사확정.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-03-09_기술스택확정_로그인방식결정.md, 2026-04-06_출시일조정_개발중간점검.md, 2026-03-23_로그인방식재논의_모임기능착수.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "정예린",
      "text_query": "정예린"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `8300.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "사용자 플로우 및 와이어프레임 초안 작성",
      "회원가입/로그인 화면 디자인",
      "베타용 온보딩 튜토리얼 화면 디자인"
    ],
    "missing": [
      "정예린이 관심사 설정 화면 디자인 확정하겠습니다 (마감 3/20)",
      "모임 탐색/생성 화면 디자인 (마감 3/27)",
      "모임 상세 화면 및 댓글 UI 디자인 (마감 4/10)",
      "스토어 등록용 스크린샷 및 소개 이미지 제작 (5/13까지)",
      "1.1 실시간 채팅 UI 디자인 (5/25까지)"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "정예린",
              "text_query": "정예린"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "정예린"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

정예린이 담당한 액션 8건이 모두 빠짐없이 포함되어 있고, 각 항목의 명칭과 마감일 등도 골든 답변과 의미상 일치한다. 추가 정보(날짜, 완료 여부 등)는 요구 범위를 벗어나지 않으므로 PASS로 판정한다. tool 호출도 owner와 category를 정확히 지정해 PASS다.

---

### M-SL02 · structured_list · 일치

#### (정답)

**질문**
김태호 담당 액션 목록을 보여줘.

**답변**

> 동결된 스냅샷 기준 김태호 담당 액션 기록은 8건이다.
> - 전체 기능 명세서 초안 작성
> - 기능 명세서 확정본 배포
> - 김태호가 출시일 조정 시나리오 3안 준비 (마감 4/6)
> - 마케팅 출시 일정 5/18 기준 재조정 (마감 4/8)
> - 베타 피드백 수집 폼 및 채널 구성
> - 베타 운영 계획 최종화
> - 1.1 업데이트(실시간 채팅) 로드맵 작성 (5/15까지)
> - 5/29 출시 회고 회의 준비 (5/28까지)

**참고 문항(출처)**
sources/modu/2026-03-02_킥오프_앱방향정의.md, sources/modu/2026-03-09_기술스택확정_로그인방식결정.md, sources/modu/2026-03-30_소셜로그인점검_일정리스크평가.md, sources/modu/2026-04-06_출시일조정_개발중간점검.md, sources/modu/2026-04-13_모임핵심기능점검_베타준비.md, sources/modu/2026-04-20_출시전최종개발점검.md, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md, sources/modu/2026-05-15_출시최종점검_1.1로드맵확정.md, memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 8,
    "order_matters": false,
    "required_items": [
      "전체 기능 명세서 초안 작성",
      "기능 명세서 확정본 배포",
      "김태호가 출시일 조정 시나리오 3안 준비 (마감 4/6)",
      "마케팅 출시 일정 5/18 기준 재조정 (마감 4/8)",
      "베타 피드백 수집 폼 및 채널 구성",
      "베타 운영 계획 최종화",
      "1.1 업데이트(실시간 채팅) 로드맵 작성 (5/15까지)",
      "5/29 출시 회고 회의 준비 (5/28까지)"
    ],
    "required_owner": "김태호",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "김태호"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
김태호 담당 액션 목록을 보여줘.

**답변**

> 김태호 담당 액션 목록은 다음과 같습니다.
>
> | 작업명                          | 주제               | 날짜       | 마감일    | 완료 여부 미확인 |
> |-------------------------------|------------------|----------|---------|--------------|
> | 출시일 조정 시나리오 3안 준비          | 출시일 조정          | 2026-03-30 | 4/6     | 미확인         |
> | 기능 명세서 확정본 배포               | -                | 2026-03-09 | -       | 미확인         |
> | 5/29 출시 회고 회의 준비              | 출시 회고 준비        | 2026-05-15 | 5/28    | 미확인         |
> | 베타 운영 계획 최종화                | 운영 계획            | 2026-04-20 | -       | 미확인         |
> | 마케팅 출시 일정 5/18 기준 재조정       | 마케팅 일정 조정       | 2026-04-06 | 4/8     | 미확인         |
> | 전체 기능 명세서 초안 작성             | 기능 명세서 작성       | 2026-03-02 | -       | 미확인         |
> | 1.1 업데이트(실시간 채팅) 로드맵 작성    | 실시간 채팅 로드맵      | 2026-05-11 | 5/15    | 미확인         |
> | 베타 피드백 수집 폼 및 채널 구성        | -                | 2026-04-13 | -       | 미확인         |

**참고 문항(반환 출처)**
2026-03-30_소셜로그인점검_일정리스크평가.md, 2026-03-09_기술스택확정_로그인방식결정.md, 2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-04-20_출시전최종개발점검.md, 2026-04-06_출시일조정_개발중간점검.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "김태호",
      "text_query": "김태호"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `10434.4 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "전체 기능 명세서 초안 작성",
      "기능 명세서 확정본 배포",
      "베타 피드백 수집 폼 및 채널 구성",
      "베타 운영 계획 최종화"
    ],
    "missing": [
      "김태호가 출시일 조정 시나리오 3안 준비 (마감 4/6)",
      "마케팅 출시 일정 5/18 기준 재조정 (마감 4/8)",
      "1.1 업데이트(실시간 채팅) 로드맵 작성 (5/15까지)",
      "5/29 출시 회고 회의 준비 (5/28까지)"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "김태호",
              "text_query": "김태호"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "김태호"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

요구된 8개 액션이 모두 빠짐없이 포함되어 있고, 각 항목의 의미도 정확히 일치한다. 표 형식으로 추가 정보(주제, 날짜 등)를 제공했으나, 목록 요구 조건을 해치지 않는다. 핵심 사실 누락이나 오류가 없다.

---

### M-SL03 · structured_list · 일치

#### (정답)

**질문**
한지민이 담당한 리스크 목록을 모두 알려줘.

**답변**

> 동결된 스냅샷 기준 한지민 담당 리스크 기록은 4건이다.
> - 소셜 로그인 추가로 인한 출시일 지연 가능성
> - 이메일 인증 스팸 문제(여전히 완전 해결 안 됨)
> - 애플 심사 리젝 가능성(첫 제출은 대개 한두 번 리젝됨)
> - 애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중)

**참고 문항(출처)**
sources/modu/2026-03-30_소셜로그인점검_일정리스크평가.md, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md, memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 4,
    "order_matters": false,
    "required_items": [
      "소셜 로그인 추가로 인한 출시일 지연 가능성",
      "이메일 인증 스팸 문제(여전히 완전 해결 안 됨)",
      "애플 심사 리젝 가능성(첫 제출은 대개 한두 번 리젝됨)",
      "애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중)"
    ],
    "required_owner": "한지민",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "risk",
        "limit": 8,
        "operation": "list",
        "owner": "한지민"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
한지민이 담당한 리스크 목록을 모두 알려줘.

**답변**

> 한지민이 담당한 리스크 목록은 다음과 같이 4건이며, 각각 일정, 출시, 심사, 이메일 인증 관련 리스크입니다.
>
> - 소셜 로그인 추가로 인한 출시일 지연 가능성
> - 애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중)
> - 애플 심사 리젝 가능성(첫 제출은 대개 한두 번 리젝됨)
> - 이메일 인증 스팸 문제(여전히 완전 해결 안 됨)

**참고 문항(반환 출처)**
2026-03-30_소셜로그인점검_일정리스크평가.md, 2026-05-11_베타결과리뷰_출시반영사항.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "risk",
      "operation": "list",
      "owner": "한지민",
      "text_query": "리스크"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `3746.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "소셜 로그인 추가로 인한 출시일 지연 가능성",
      "이메일 인증 스팸 문제(여전히 완전 해결 안 됨)",
      "애플 심사 리젝 가능성(첫 제출은 대개 한두 번 리젝됨)",
      "애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중)"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "risk",
              "operation": "list",
              "owner": "한지민",
              "text_query": "리스크"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "risk",
          "limit": 8,
          "operation": "list",
          "owner": "한지민"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

골든 답변의 4가지 리스크를 모두 빠짐없이 포함하고 있으며, 표현 순서만 다를 뿐 의미상 동일하다. 추가적이거나 잘못된 정보도 없다. tool call 역시 owner, category 등 핵심 인자를 모두 포함해 PASS로 판단한다.

---

### M-SL04 · structured_list · 일치

#### (정답)

**질문**
이수진이 담당한 결정 목록을 보여줘.

**답변**

> 동결된 스냅샷 기준 이수진 담당 결정 기록은 2건이다.
> - 백엔드를 Node.js + PostgreSQL(PostGIS)로 확정한다.
> - 이메일 발송 서비스를 AWS SES로 확정한다.

**참고 문항(출처)**
sources/modu/2026-03-09_기술스택확정_로그인방식결정.md, sources/modu/2026-03-16_회원시스템점검_관심사확정.md, memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 2,
    "order_matters": false,
    "required_items": [
      "백엔드를 Node.js + PostgreSQL(PostGIS)로 확정한다.",
      "이메일 발송 서비스를 AWS SES로 확정한다."
    ],
    "required_owner": "이수진",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "decision",
        "limit": 8,
        "operation": "list",
        "owner": "이수진"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
이수진이 담당한 결정 목록을 보여줘.

**답변**

> 이수진이 담당한 결정 목록은 다음과 같다:
>
> - 이메일 발송 서비스를 AWS SES로 확정한다. (2026-03-16)
> - 백엔드를 Node.js + PostgreSQL(PostGIS)로 확정한다. (2026-03-09)

**참고 문항(반환 출처)**
2026-03-16_회원시스템점검_관심사확정.md, 2026-03-09_기술스택확정_로그인방식결정.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "decision",
      "operation": "list",
      "owner": "이수진",
      "text_query": "이수진"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `3301.8 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "백엔드를 Node.js + PostgreSQL(PostGIS)로 확정한다.",
      "이메일 발송 서비스를 AWS SES로 확정한다."
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "decision",
              "operation": "list",
              "owner": "이수진",
              "text_query": "이수진"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "decision",
          "limit": 8,
          "operation": "list",
          "owner": "이수진"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

골든 답변의 두 결정 모두 정확히 포함되어 있고, 추가적인 날짜 정보는 오류가 아니며 요구된 목록을 모두 충족한다. 핵심 사실 누락이나 잘못된 정보가 없다.

---

### M-SL05 · structured_list · 일치

#### (정답)

**질문**
이수진이 담당한 이슈 목록을 알려줘.

**답변**

> 동결된 스냅샷 기준 이수진 담당 이슈 기록은 1건이다.
> - 정식 출시 서버 부하 규모 예측치 불확실 (실측 후 스케일링 판단)

**참고 문항(출처)**
sources/modu/2026-05-15_출시최종점검_1.1로드맵확정.md, memory_snapshots/modu.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 1,
    "order_matters": false,
    "required_items": [
      "정식 출시 서버 부하 규모 예측치 불확실 (실측 후 스케일링 판단)"
    ],
    "required_owner": "이수진",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "issue",
        "limit": 8,
        "operation": "list",
        "owner": "이수진"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
이수진이 담당한 이슈 목록을 알려줘.

**답변**

> 이수진이 담당한 이슈는 "정식 출시 서버 부하 규모 예측치 불확실 (실측 후 스케일링 판단)" 한 건입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "issue",
      "operation": "list",
      "owner": "이수진",
      "text_query": "이슈"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2438.1 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "정식 출시 서버 부하 규모 예측치 불확실 (실측 후 스케일링 판단)"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "issue",
              "operation": "list",
              "owner": "이수진",
              "text_query": "이슈"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "issue",
          "limit": 8,
          "operation": "list",
          "owner": "이수진"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 이수진 담당 이슈의 전체 목록(1건)을 정확히 제시했고, 이슈 내용도 일치한다. 수량도 명확히 언급했다. tool 호출 역시 owner와 category를 정확히 지정해 의미를 충족한다.

---

### M-OV01 · overview · 일치

#### (정답)

**질문**
Modu 프로젝트 전체 현황을 간단히 브리핑해줘.

**답변**

> Modu는 5월 18일 출시를 확정했고 실시간 채팅은 6월 8일 1.1 업데이트에 편입했다. iOS 심사와 서버 부하가 아직 불확실하며 출시·모니터링·회고 준비 액션이 기록돼 있다.

**참고 문항(출처)**
overview_snapshots/modu.json, memory_snapshots/modu.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "min_required_facts": 4,
    "required_facts": [
      "5월 18일 출시",
      "6월 8일 1.1 실시간 채팅",
      "iOS 승인 대기",
      "출시 후 모니터링"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
Modu 프로젝트 전체 현황을 간단히 브리핑해줘.

**답변**

> Modu 프로젝트는 앱 콘셉트, 핵심 기능, 기술 스택, 로그인 방식, 채팅 기능 등 주요 결정이 완료되었고, 출시일은 2026년 5월 18일로 1주 연기해 확정된 상태입니다. 소셜 로그인 3종 추가와 이메일 인증 스팸 문제, iOS 앱스토어 승인 대기 등 일정과 리스크가 존재하며, 베타 테스트를 통해 심각 버그는 해결했고 경미 버그는 병행 수정 중입니다. 실시간 채팅은 MVP에서 제외하고 6월 8일 1.1 업데이트 최우선 기능으로 계획 중이며, 출시 후 서버 부하 모니터링과 5월 29일 회고 회의 준비도 진행 중입니다.
>
> **요약: 주요 결정 완료, 5월 18일 출시 예정, 실시간 채팅은 1.1 업데이트로 연기, 일정과 리스크 관리 중, 베타 테스트 완료 및 버그 수정 중**입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `4253.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": false
      },
      {
        "category": "action",
        "count": 55,
        "matched": false
      },
      {
        "category": "issue",
        "count": 16,
        "matched": false
      },
      {
        "category": "risk",
        "count": 6,
        "matched": false
      }
    ],
    "matched": [
      "5월 18일 출시"
    ],
    "missing": [
      "6월 8일 1.1 실시간 채팅",
      "iOS 승인 대기",
      "출시 후 모니터링"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.98` · semantic 검색 인자 `N/A`

실제 답변은 5월 18일 출시, 6월 8일 1.1 실시간 채팅 업데이트, iOS 승인 대기, 출시 후 서버 부하 모니터링 등 골든 답변의 모든 핵심 사실을 포함하고 있다. 추가로 베타 테스트, 버그 수정 등 부가 정보도 있으나, 요구된 핵심 현황 요약을 모두 충족한다. 중요한 오류나 누락이 없다.

---

### M-OV02 · overview · 일치

#### (정답)

**질문**
카테고리별 기록 수와 현재 대표 액션을 함께 정리해줘.

**답변**

> 동결 스냅샷의 활성 기록은 결정 26건, 액션 55건, 이슈 16건, 리스크 6건이다. 대표 액션에는 앱스토어 심사 추적, 5/18 안드로이드 출시, 서버 부하 모니터링 준비, WebSocket 개발 착수, 1.1 채팅 UI 디자인이 있다.

**참고 문항(출처)**
overview_snapshots/modu.json, memory_snapshots/modu.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "min_required_facts": 5,
    "required_facts": [
      "결정 26",
      "액션 55",
      "이슈 16",
      "리스크 6",
      "5/18 안드로이드 출시"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 현재 대표 액션을 함께 정리해줘.

**답변**

> 카테고리별 기록 수는 **결정 26건, 액션 55건, 이슈 16건, 리스크 6건**이며, 현재 대표 액션(완료 여부 불명)은 다음과 같습니다.
>
> | 카테고리 | 대표 액션 내용                      | 담당자   | 완료 상태  |
> |----------|----------------------------------|----------|------------|
> | 액션     | 1.1 실시간 채팅 UI 디자인 (5/25까지) | 정예린   | 완료 여부 불명 |
> | 액션     | 5/29 출시 회고 회의 준비 (5/28까지)  | 김태호   | 완료 여부 불명 |
> | 액션     | 실시간 채팅 WebSocket 개발 착수 (5/19까지) | 이수진   | 완료 여부 불명 |
> | 액션     | 출시 후 서버 부하 모니터링 체계 준비 (5/17까지) | 이수진   | 완료 여부 불명 |
> | 액션     | 5/18 안드로이드 출시 실행           | 박현우   | 완료 여부 불명 |
>
> 현재 열려있는 액션은 없으며, 위 액션들은 완료 여부가 기록에 명확히 확인되지 않습니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `5986.2 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": true
      },
      {
        "category": "action",
        "count": 55,
        "matched": true
      },
      {
        "category": "issue",
        "count": 16,
        "matched": true
      },
      {
        "category": "risk",
        "count": 6,
        "matched": true
      }
    ],
    "matched": [
      "결정 26",
      "액션 55",
      "이슈 16",
      "리스크 6",
      "5/18 안드로이드 출시"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `N/A`

카테고리별 기록 수(결정 26, 액션 55, 이슈 16, 리스크 6)와 대표 액션(5/18 안드로이드 출시 포함)을 모두 정확히 제시했다. 대표 액션의 완료 여부가 불명이라고 명시한 것도 허용 범위 내 설명이다. 요구된 핵심 사실을 모두 충족한다.

---

### M-OV03 · overview · 일치

#### (정답)

**질문**
경영진이 한눈에 볼 수 있도록 프로젝트 상황을 요약해줘.

**답변**

> 핵심 기능과 기술 결정은 완료됐고 5월 18일 출시를 준비 중이다. 소셜 로그인·애플 심사·이메일 스팸이 주요 위험이며, 실시간 채팅은 1.1로 미루고 출시 후 지표 모니터링과 회고를 계획했다.

**참고 문항(출처)**
overview_snapshots/modu.json, memory_snapshots/modu.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "min_required_facts": 5,
    "required_facts": [
      "5월 18일",
      "소셜 로그인",
      "애플 심사",
      "이메일 스팸",
      "실시간 채팅 1.1"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
경영진이 한눈에 볼 수 있도록 프로젝트 상황을 요약해줘.

**답변**

> 경영진용 프로젝트 상황 요약은 다음과 같습니다.
>
> - **출시일은 2026년 5월 18일로 1주 연기 확정**되었으며, iOS 앱은 앱스토어 승인 대기 중으로 출시 시점이 불확실함.
> - **소셜 로그인 3종(카카오·구글·애플) 추가**로 일정 부담과 애플 심사 리스크 존재, 이메일 인증 스팸 문제도 완전 해결되지 않아 사용자 이탈 우려 있음.
> - 베타 테스트(5/2~5/8, 100명, 강남·판교 한정)에서 심각 버그 2건 사전 해결, 경미 버그는 병행 수정 중.
> - 실시간 채팅 기능은 MVP에서 제외하고 6월 8일 1.1 업데이트 최우선 기능으로 계획 중.
> - 출시 후 서버 부하 모니터링 체계 준비 및 사용자 지표 모니터링 예정, 5월 29일 회고 회의 준비 중.
> - 현재 주요 미완료 작업으로는 5/18 안드로이드 출시 실행, 실시간 채팅 WebSocket 개발 착수(5/19까지), 서버 부하 모니터링 체계 준비(5/17까지), 1.1 실시간 채팅 UI 디자인(5/25까지), 5/29 출시 회고 회의 준비(5/28까지) 등이 있음.
>
> 전체적으로 출시 준비는 막바지 단계이며, 일부 리스크와 미완료 작업이 있으나 계획대로 진행 중입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `10243.6 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": false
      },
      {
        "category": "action",
        "count": 55,
        "matched": false
      },
      {
        "category": "issue",
        "count": 16,
        "matched": false
      },
      {
        "category": "risk",
        "count": 6,
        "matched": false
      }
    ],
    "matched": [
      "5월 18일",
      "소셜 로그인",
      "애플 심사"
    ],
    "missing": [
      "이메일 스팸",
      "실시간 채팅 1.1"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.98` · semantic 검색 인자 `N/A`

요구된 핵심 사실(5월 18일 출시, 소셜 로그인, 애플 심사, 이메일 스팸, 실시간 채팅 1.1 업데이트 계획)이 모두 포함되어 있고, 추가로 베타 테스트, 서버 부하 모니터링 등 실제 상황에 대한 상세 정보도 제공되어 있다. 중요한 오류나 누락이 없으므로 PASS로 판정한다.

---

### M-OV04 · overview · 부분일치

#### (정답)

**질문**
결정·액션·이슈·리스크 관점에서 현재 프로젝트 상태를 정리해줘.

**답변**

> 활성 기록은 결정 26, 액션 55, 이슈 16, 리스크 6건이다. 5월 18일 출시와 6월 8일 1.1 실시간 채팅 일정은 확정됐고, iOS 승인 시점과 서버 부하는 아직 불확실하다.

**참고 문항(출처)**
overview_snapshots/modu.json, memory_snapshots/modu.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "min_required_facts": 8,
    "required_facts": [
      "결정 26",
      "액션 55",
      "이슈 16",
      "리스크 6",
      "5월 18일",
      "6월 8일",
      "iOS",
      "서버 부하"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
결정·액션·이슈·리스크 관점에서 현재 프로젝트 상태를 정리해줘.

**답변**

> 현재 프로젝트 상태는 다음과 같이 정리할 수 있습니다.
>
> - **결정(Decision)**: 앱 콘셉트, 핵심 기능, 기술 스택, 로그인 방식, 채팅 기능 등 주요 결정이 완료되었으며, 출시일은 2026년 5월 18일로 1주 연기 확정됨(총 26건 결정).
> - **액션(Action)**: 총 55건 중 현재 열려있는 액션은 없으나, 완료 여부가 불명확한 작업(예: 1.1 실시간 채팅 UI 디자인, 5/29 출시 회고 회의 준비, 실시간 채팅 WebSocket 개발 착수, 서버 부하 모니터링 체계 준비, 5/18 안드로이드 출시 실행 등)이 있음.
> - **이슈(Issue)**: 16건의 이슈가 존재하며, 소셜 로그인 추가에 따른 일정 부담과 애플 심사 리스크, 이메일 인증 스팸 문제로 인한 사용자 이탈 우려 등이 포함됨.
> - **리스크(Risk)**: 6건의 리스크가 보고되었으며, iOS 앱스토어 승인 지연과 서버 부하 예측 불확실성이 주요 리스크임.
>
> 요약하면, **주요 결정은 완료되었고 출시 준비가 진행 중이나, 일부 액션의 완료 상태가 불명확하며 소셜 로그인과 인증 관련 이슈 및 iOS 승인 지연과 서버 부하 리스크가 남아 있는 상황**입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `10447.8 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": false
      },
      {
        "category": "action",
        "count": 55,
        "matched": false
      },
      {
        "category": "issue",
        "count": 16,
        "matched": false
      },
      {
        "category": "risk",
        "count": 6,
        "matched": false
      }
    ],
    "matched": [
      "5월 18일",
      "iOS",
      "서버 부하"
    ],
    "missing": [
      "결정 26",
      "액션 55",
      "이슈 16",
      "리스크 6",
      "6월 8일"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `N/A`

결정 26·액션 55·이슈 16·리스크 6, 5월 18일, iOS 승인과 서버 부하 불확실성은 정확하다. 6월 8일 1.1 실시간 채팅 일정만 빠졌다. 자동 Judge가 근거 없다고 본 나머지 일정과 액션은 overview 스냅샷에 존재한다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "core_facts_missing": [
    "6월 8일 1.1 실시간 채팅 일정"
  ],
  "failure_codes": [
    "MISSING_FACT"
  ]
}
```

---

### M-MX01 · mixed_tools · 일치

#### (정답)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 프로젝트 전체 현황, 그리고 베타 7일 리텐션을 함께 알려줘.

**답변**

> 활성 기록은 결정 26건, 액션 55건, 이슈 16건, 리스크 6건이다. 5/18 안드로이드 출시, 서버 부하 모니터링, 1.1 실시간 채팅 준비가 대표 액션으로 기록돼 있다. 베타 7일 리텐션은 64%였다.

**참고 문항(출처)**
overview_snapshots/modu.json, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md

**기대 도구** `get_project_overview, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "required_terms": [
      "5/18 안드로이드 출시",
      "64%"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    },
    {
      "args_semantics": "베타 7일 리텐션",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 프로젝트 전체 현황, 그리고 베타 7일 리텐션을 함께 알려줘.

**답변**

> 프로젝트 전체 현황은 카테고리별 기록 수가 **결정 26건, 액션 55건, 이슈 16건, 리스크 6건**이며, 대표 액션으로는 "1.1 실시간 채팅 UI 디자인(정예린, 5/25까지)", "5/29 출시 회고 회의 준비(김태호, 5/28까지)", "실시간 채팅 WebSocket 개발 착수(이수진, 5/19까지)" 등이 있습니다. 베타 7일 리텐션은 **64%**로 초기 앱치고 나쁘지 않은 수준입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-04-13_모임핵심기능점검_베타준비.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-06_출시일조정_개발중간점검.md, 2026-04-20_출시전최종개발점검.md

**실제 도구** `get_project_overview, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  },
  {
    "args": {
      "query": "베타 7일 리텐션"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `5643.4 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": true
      },
      {
        "category": "action",
        "count": 55,
        "matched": true
      },
      {
        "category": "issue",
        "count": 16,
        "matched": true
      },
      {
        "category": "risk",
        "count": 6,
        "matched": true
      }
    ],
    "matched": [
      "64%"
    ],
    "missing": [
      "5/18 안드로이드 출시"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      },
      {
        "actual_candidates": [
          {
            "args": {
              "query": "베타 7일 리텐션"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "베타 7일 리텐션",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.99` · semantic 검색 인자 `PASS`

카테고리 수 26·55·16·6, 유효한 대표 액션 3개, 7일 리텐션 64%를 모두 정확히 답했다. 골든 계약이 대표 액션 중 5/18 안드로이드 출시만 고정한 것은 질문 의도보다 좁아 과적합 판정을 만들므로 의미 기준 PASS로 재판정했다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PASS_

---

### M-MX02 · mixed_tools · 일치

#### (정답)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 전체 상황, 그리고 모임 알림 지연 개선 결과를 같이 요약해줘.

**답변**

> 활성 기록은 결정 26건, 액션 55건, 이슈 16건, 리스크 6건이다. 5/18 출시, 서버 부하 모니터링, 1.1 WebSocket 개발 착수 등이 대표 액션으로 기록돼 있다. 모임 알림 지연은 이수진이 푸시 큐 처리 방식을 고쳐 평균 8초에서 1초 이내로 줄였다.

**참고 문항(출처)**
overview_snapshots/modu.json, sources/modu/2026-05-15_출시최종점검_1.1로드맵확정.md

**기대 도구** `get_project_overview, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 55,
      "decision": 26,
      "issue": 16,
      "risk": 6
    },
    "required_terms": [
      "WebSocket",
      "이수진",
      "푸시 큐",
      "8초",
      "1초"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    },
    {
      "args_semantics": "알림 지연 원인과 개선 수치",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 전체 상황, 그리고 모임 알림 지연 개선 결과를 같이 요약해줘.

**답변**

> 전체 상황은 다음과 같으며, 모임 알림 지연 개선 결과도 포함합니다.
>
> - 카테고리별 기록 수:
>   - 결정(decision): 26건
>   - 액션(action): 55건
>   - 이슈(issue): 16건
>   - 리스크(risk): 6건
>
> - 대표 액션 예시:
>   - 1.1 실시간 채팅 UI 디자인 (정예린, 5/25까지)
>   - 5/29 출시 회고 회의 준비 (김태호, 5/28까지)
>   - 실시간 채팅 WebSocket 개발 착수 (이수진, 5/19까지)
>   - 출시 후 서버 부하 모니터링 체계 준비 (이수진, 5/17까지)
>   - 5/18 안드로이드 출시 실행 (박현우)
>
> - 모임 알림 지연 개선 결과:
>   - 원인은 푸시 큐 처리 방식 문제였음
>   - 개선 후 알림 지연이 평균 8초에서 1초 이내로 크게 단축됨
>   - 관련 액션으로 5/14까지 모임 알림 지연 원인 분석 및 개선 작업이 진행됨(담당: 이수진)
>   - 모임 알림 지연 문제는 베타 테스트 중 11명 이상이 언급한 주요 이슈였으며, 출시 전까지 개선하기로 결정됨(담당: 김태호)
>
> 요약하면, 프로젝트는 주요 결정과 액션이 활발히 진행 중이며, 특히 모임 알림 지연 문제는 원인 분석과 개선 조치로 평균 지연 시간을 8초에서 1초 이내로 줄여 성공적으로 개선된 상태입니다.

**참고 문항(반환 출처)**
2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-06_출시일조정_개발중간점검.md, 2026-04-13_모임핵심기능점검_베타준비.md, 2026-03-23_로그인방식재논의_모임기능착수.md

**실제 도구** `get_project_overview, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  },
  {
    "args": {
      "alternate_queries": [
        "모임 알림 지연 문제 해결 현황",
        "모임 알림 지연 개선 효과"
      ],
      "query": "모임 알림 지연 개선 결과"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `10344.7 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 26,
        "matched": false
      },
      {
        "category": "action",
        "count": 55,
        "matched": false
      },
      {
        "category": "issue",
        "count": 16,
        "matched": false
      },
      {
        "category": "risk",
        "count": 6,
        "matched": false
      }
    ],
    "matched": [
      "WebSocket",
      "이수진",
      "푸시 큐",
      "8초",
      "1초"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      },
      {
        "actual_candidates": [
          {
            "args": {
              "alternate_queries": [
                "모임 알림 지연 문제 해결 현황",
                "모임 알림 지연 개선 효과"
              ],
              "query": "모임 알림 지연 개선 결과"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "알림 지연 원인과 개선 수치",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.98` · semantic 검색 인자 `PASS`

질문이 요구한 카테고리별 기록 수, 대표 액션, 모임 알림 지연 개선의 원인·담당자·수치 등 모든 핵심 사실을 정확히 포함하고 있다. 추가 설명(베타테스트 언급, 개선 일정 등)은 본질적 요구를 벗어나지 않으며, 오히려 맥락을 보완한다. tool 호출 쿼리도 의미를 잘 보존한다.

---

### M-MX03 · mixed_tools · 일치

#### (정답)

**질문**
한지민 담당 리스크를 전부 보여주고, 애플 심사 리스크가 출시와 어떤 관계인지 설명해줘.

**답변**

> 한지민 담당 리스크는 4건이다:
> - 소셜 로그인 추가로 인한 출시일 지연 가능성
> - 이메일 인증 스팸 문제(여전히 완전 해결 안 됨)
> - 애플 심사 리젝 가능성(첫 제출은 대개 한두 번 리젝됨)
> - 애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중)
> 애플 로그인 제공은 심사 조건이고 첫 제출 리젝 가능성과 승인 지연이 5/18 iOS 출시에 영향을 줄 수 있다.

**참고 문항(출처)**
sources/modu/2026-03-30_소셜로그인점검_일정리스크평가.md, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md

**기대 도구** `query_structured_memory, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "4",
      "한지민",
      "애플",
      "5/18",
      "심사"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "risk",
        "limit": 8,
        "operation": "list",
        "owner": "한지민"
      },
      "name": "query_structured_memory"
    },
    {
      "args_semantics": "애플 심사 리스크와 출시 영향",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
한지민 담당 리스크를 전부 보여주고, 애플 심사 리스크가 출시와 어떤 관계인지 설명해줘.

**답변**

> **한지민 담당 리스크는 다음과 같다:**
>
> - 소셜 로그인 추가로 인한 출시일 지연 가능성 (2026-03-30)
> - 애플 심사 리젝 가능성 (첫 제출은 대개 한두 번 리젝됨) (2026-03-30)
> - 애플 심사 리젝 시 5/18 출시 영향 (심사 결과 대기 중) (2026-05-11)
> - 이메일 인증 스팸 문제(여전히 완전 해결 안 됨) (2026-03-30)
>
> **애플 심사 리스크와 출시와의 관계는 다음과 같다:**
>
> - iOS 앱스토어 심사에서 소셜 로그인 제공 시 애플 로그인을 반드시 포함해야 하며, 이를 충족하지 못하면 심사에서 리젝된다.
> - 애플 심사 리젝 가능성은 첫 제출 시 보통 한두 번 발생하는 것으로 예상된다.
> - 5월 12일에 앱스토어 심사를 제출했고 한 차례 리젝되어 5월 14일 재제출 후 심사 중이다.
> - 애플 심사에서 리젝될 경우 5월 18일 출시 일정에 영향을 줄 수 있는 리스크로 공식 등록되어 있으며, 심사 결과에 따라 출시 시점이 불확실하다.
> - 다만, 현재 리젝 사유는 경미하여 재제출로 해결될 가능성이 높다고 평가된다.
>
> 즉, **애플 심사 리젝 리스크는 iOS 출시 일정에 직접적인 영향을 미치며, 심사 결과에 따라 5월 18일 출시가 지연될 가능성이 존재한다.**

**참고 문항(반환 출처)**
2026-03-30_소셜로그인점검_일정리스크평가.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-13_모임핵심기능점검_베타준비.md, 2026-03-16_회원시스템점검_관심사확정.md, 2026-03-09_기술스택확정_로그인방식결정.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "alternate_queries": [
        "한지민 담당 리스크",
        "한지민 리스크 목록"
      ],
      "query": "한지민 리스크"
    },
    "name": "search_project_evidence"
  },
  {
    "args": {
      "alternate_queries": [
        "애플 심사 리스크와 출시 관계",
        "애플 심사 리스크가 출시 일정에 미치는 영향"
      ],
      "query": "애플 심사 리스크 출시 관계"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `11831.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "4",
      "한지민",
      "애플",
      "5/18",
      "심사"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": false,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": false
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "effective_args_pass": false,
    "exact_args_pass": false,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "risk",
          "limit": 8,
          "operation": "list",
          "owner": "한지민"
        }
      },
      {
        "actual_candidates": [
          {
            "args": {
              "alternate_queries": [
                "한지민 담당 리스크",
                "한지민 리스크 목록"
              ],
              "query": "한지민 리스크"
            },
            "name": "search_project_evidence"
          },
          {
            "args": {
              "alternate_queries": [
                "애플 심사 리스크와 출시 관계",
                "애플 심사 리스크가 출시 일정에 미치는 영향"
              ],
              "query": "애플 심사 리스크 출시 관계"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "애플 심사 리스크와 출시 영향",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": false
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.98` · semantic 검색 인자 `PASS`

한지민 담당 리스크 4건을 모두 정확히 제시했고, 애플 심사 리스크가 5/18 출시 일정에 미치는 영향도 구체적으로 설명했다. 추가로 심사 제출 및 리젝/재제출 상황 등 세부사항이 있으나, 이는 골든 답변의 범위를 벗어나지 않고 핵심 요구를 모두 충족한다. 도구 호출 쿼리도 의미를 잘 보존했다.

---

### M-MX04 · mixed_tools · 부분일치

#### (정답)

**질문**
이수진 담당 결정 목록과 AWS SES를 선택한 이유를 함께 알려줘.

**답변**

> 이수진 담당 결정은 2건이다:
> - 백엔드를 Node.js + PostgreSQL(PostGIS)로 확정한다.
> - 이메일 발송 서비스를 AWS SES로 확정한다.
> AWS SES는 비용이 저렴하고 기존 인프라가 AWS 기반이라 연동이 쉬워 선택했다.

**참고 문항(출처)**
sources/modu/2026-03-09_기술스택확정_로그인방식결정.md, sources/modu/2026-03-16_회원시스템점검_관심사확정.md

**기대 도구** `query_structured_memory, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "2",
      "PostgreSQL",
      "AWS SES",
      "비용",
      "AWS"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "decision",
        "limit": 8,
        "operation": "list",
        "owner": "이수진"
      },
      "name": "query_structured_memory"
    },
    {
      "args_semantics": "AWS SES 선택 이유",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
이수진 담당 결정 목록과 AWS SES를 선택한 이유를 함께 알려줘.

**답변**

> **이수진 담당 결정 목록에는 백엔드 기술 스택 선정, 이메일 발송 서비스 선정, 이메일 인증 스팸 이슈 개선, 모임 데이터 모델 및 위치 검색 API 설계, 소셜 로그인 백엔드 인증 처리 등이 포함되며, AWS SES를 이메일 발송 서비스로 선택한 이유는 비용 효율성과 기존 AWS 인프라와의 연동 용이성 때문이다.**
>
> 근거 상세:
> - 이수진 담당 결정 및 액션 주요 내용
>   - 백엔드를 Node.js + PostgreSQL(PostGIS)로 확정 (2026-03-09)
>   - 이메일 발송 서비스를 AWS SES로 확정 (2026-03-16)
>   - 이메일 인증 스팸 이슈 개선(SPF/DKIM 설정) 진행 (마감 3/20)
>   - 모임 데이터 모델 및 위치 검색 API 설계 (마감 3/23)
>   - 소셜 로그인 백엔드 인증 처리(OAuth) (마감 3/30)
> - AWS SES 선택 이유
>   - 비용 효율적임
>   - 기존 AWS 인프라와 연동이 용이함
> - 원문 맥락에서 이수진은 이메일 인증 기반 회원 시스템 설계 및 DB 스키마를 완료했고, 이메일 발송은 AWS SES로 정했으며, 비용과 인프라 연동 측면에서 유리하다고 설명함
>
> 따라서, 이수진은 백엔드와 이메일 관련 주요 기술 결정과 구현을 담당했고, AWS SES는 비용과 인프라 연동 편의성 때문에 선택되었다.

**참고 문항(반환 출처)**
2026-03-16_회원시스템점검_관심사확정.md, 2026-03-02_킥오프_앱방향정의.md, 2026-03-23_로그인방식재논의_모임기능착수.md, 2026-03-30_소셜로그인점검_일정리스크평가.md, 2026-05-15_출시최종점검_1.1로드맵확정.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "alternate_queries": [
        "이수진 담당 결정 목록",
        "이수진 담당 결정 내역"
      ],
      "query": "이수진 담당 결정"
    },
    "name": "search_project_evidence"
  },
  {
    "args": {
      "alternate_queries": [
        "AWS SES를 선택한 이유",
        "왜 AWS SES를 선택했나"
      ],
      "query": "AWS SES 선택 이유"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `10364.5 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "2",
      "PostgreSQL",
      "AWS SES",
      "비용",
      "AWS"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": false,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": false
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "effective_args_pass": false,
    "exact_args_pass": false,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "decision",
          "limit": 8,
          "operation": "list",
          "owner": "이수진"
        }
      },
      {
        "actual_candidates": [
          {
            "args": {
              "alternate_queries": [
                "이수진 담당 결정 목록",
                "이수진 담당 결정 내역"
              ],
              "query": "이수진 담당 결정"
            },
            "name": "search_project_evidence"
          },
          {
            "args": {
              "alternate_queries": [
                "AWS SES를 선택한 이유",
                "왜 AWS SES를 선택했나"
              ],
              "query": "AWS SES 선택 이유"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "AWS SES 선택 이유",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": false
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `PASS`

정답인 Node.js+PostgreSQL(PostGIS), AWS SES와 선택 이유는 맞았다. 그러나 이메일 스팸 개선·데이터 모델/API·OAuth 처리 액션을 결정 목록에 섞었고, 필수 구조화 도구도 호출하지 않았다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "contradictions": [
    "실제 action 3개를 이수진 담당 decision 목록에 포함"
  ],
  "failure_codes": [
    "WRONG_FACT"
  ]
}
```

---

### M-SE01 · semantic_boundary · 일치

#### (정답)

**질문**
카카오·구글·애플 앱 로그인 SDK 연동을 맡은 사람은 누구야?

**답변**

> 세 앱 로그인 연동은 박현우가 담당했다. 이수진은 앱 SDK가 아니라 백엔드 OAuth 처리와 통합 테스트 담당이다.

**참고 문항(출처)**
sources/modu/2026-03-23_로그인방식재논의_모임기능착수.md, sources/modu/2026-03-30_소셜로그인점검_일정리스크평가.md

**기대 도구** `search_project_evidence` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "박현우",
      "이수진",
      "OAuth"
    ],
    "type": "semantic_facts"
  },
  "tool_calls": [
    {
      "args_semantics": "질문 전체 의미를 보존",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
카카오·구글·애플 앱 로그인 SDK 연동을 맡은 사람은 누구야?

**답변**

> 카카오·구글·애플 앱 로그인 SDK 연동은 **박현우가 카카오·구글·애플 로그인 연동을 담당**하고 있으며, 이수진이 애플 OAuth 처리 및 소셜 로그인 통합 테스트를 맡고 있다.

**참고 문항(반환 출처)**
2026-03-23_로그인방식재논의_모임기능착수.md, 2026-03-30_소셜로그인점검_일정리스크평가.md, 2026-03-09_기술스택확정_로그인방식결정.md, 2026-04-20_출시전최종개발점검.md, 2026-03-02_킥오프_앱방향정의.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "alternate_queries": [
        "구글 앱 로그인 SDK 연동 담당자",
        "애플 앱 로그인 SDK 연동 담당자"
      ],
      "query": "카카오 앱 로그인 SDK 연동 담당자"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `5750.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "박현우",
      "이수진",
      "OAuth"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "semantic_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "alternate_queries": [
                "구글 앱 로그인 SDK 연동 담당자",
                "애플 앱 로그인 SDK 연동 담당자"
              ],
              "query": "카카오 앱 로그인 SDK 연동 담당자"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "질문 전체 의미를 보존",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.99` · semantic 검색 인자 `PASS`

세 앱 SDK 연동 담당자를 박현우로 정확히 답했다. 이수진의 애플 OAuth 처리와 통합 테스트라는 설명도 3/30 원문에 그대로 있고, 3/23의 백엔드 OAuth 역할과 모순되지 않는다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PASS_

---

### M-SE02 · semantic_boundary · 일치

#### (정답)

**질문**
Modu 개발에 투입된 총예산은 얼마야?

**답변**

> 문서에서 확인할 수 없다. 일정과 담당자는 있지만 총예산이나 프로젝트 비용은 기록되지 않았다.

**참고 문항(출처)**
sources/modu/2026-03-02_킥오프_앱방향정의.md, sources/modu/2026-03-09_기술스택확정_로그인방식결정.md, sources/modu/2026-03-16_회원시스템점검_관심사확정.md, sources/modu/2026-03-23_로그인방식재논의_모임기능착수.md, sources/modu/2026-03-30_소셜로그인점검_일정리스크평가.md, sources/modu/2026-04-06_출시일조정_개발중간점검.md, sources/modu/2026-04-13_모임핵심기능점검_베타준비.md, sources/modu/2026-04-20_출시전최종개발점검.md, sources/modu/2026-05-11_베타결과리뷰_출시반영사항.md, sources/modu/2026-05-15_출시최종점검_1.1로드맵확정.md

**기대 도구** `search_project_evidence` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "must_abstain": true,
    "required_terms": [
      "확인",
      "없"
    ],
    "type": "semantic_facts"
  },
  "tool_calls": [
    {
      "args_semantics": "질문 전체 의미를 보존",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
Modu 개발에 투입된 총예산은 얼마야?

**답변**

> 기록에서 Modu 개발에 투입된 총예산에 관한 정보는 확인되지 않는다.

**참고 문항(반환 출처)**
2026-03-09_기술스택확정_로그인방식결정.md, 2026-03-02_킥오프_앱방향정의.md, 2026-05-15_출시최종점검_1.1로드맵확정.md, 2026-05-11_베타결과리뷰_출시반영사항.md, 2026-04-06_출시일조정_개발중간점검.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "query": "Modu 개발 총예산"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `2779.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "확인"
    ],
    "missing": [
      "없"
    ],
    "must_abstain": true,
    "strict_text_pass": false,
    "type": "semantic_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "query": "Modu 개발 총예산"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "질문 전체 의미를 보존",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 총예산 정보가 확인되지 않는다고 명확히 밝혀 must_abstain 조건을 충족한다. 골든 답변의 핵심 사실(총예산 정보 부존재)과 의미가 동일하다. 검색 쿼리도 질문의 의미를 잘 반영했다.

---

### C-SC01 · structured_count · 일치

#### (정답)

**질문**
현재 CS-Bot 프로젝트의 액션 기록은 총 몇 개야?

**답변**

> 동결된 csbot 메모리 스냅샷 기준 액션 기록은 총 30건이다.

**참고 문항(출처)**
memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 30,
    "required_terms": [
      "30"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "operation": "count"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
현재 CS-Bot 프로젝트의 액션 기록은 총 몇 개야?

**답변**

> 현재 CS-Bot 프로젝트의 액션 기록은 총 **30개**입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "count",
      "text_query": "액션"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2562.0 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "30"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "count",
              "text_query": "액션"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "operation": "count"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 액션 기록의 총 개수(30개)를 정확히 명시했고, 의미상 골든 답변과 동일하다. 도구 호출에서도 category가 'action'으로 맞게 지정되어 있어 PASS이다.

---

### C-SC02 · structured_count · 일치

#### (정답)

**질문**
박서연이 담당한 액션은 몇 개야?

**답변**

> 동결된 csbot 메모리 스냅샷 기준 박서연 담당 액션 기록은 총 7건이다.

**참고 문항(출처)**
memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 7,
    "required_terms": [
      "7"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "operation": "count",
        "owner": "박서연"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
박서연이 담당한 액션은 몇 개야?

**답변**

> 박서연이 담당한 액션은 총 **7개**입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "count",
      "owner": "박서연",
      "text_query": "박서연"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2211.2 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "7"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "count",
              "owner": "박서연",
              "text_query": "박서연"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "operation": "count",
          "owner": "박서연"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 박서연 담당 액션의 개수(7개)를 정확히 명시했고, 의미상 골든 답변과 동일하다. tool call 역시 owner와 category를 정확히 지정해 PASS다.

---

### C-SC03 · structured_count · 일치

#### (정답)

**질문**
강다은 담당 액션 수를 알려줘.

**답변**

> 동결된 csbot 메모리 스냅샷 기준 강다은 담당 액션 기록은 총 4건이다.

**참고 문항(출처)**
memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 4,
    "required_terms": [
      "4"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "operation": "count",
        "owner": "강다은"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
강다은 담당 액션 수를 알려줘.

**답변**

> 강다은 담당 액션 수는 총 4개입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "count",
      "owner": "강다은",
      "text_query": "강다은"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `1993.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "4"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "count",
              "owner": "강다은",
              "text_query": "강다은"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "operation": "count",
          "owner": "강다은"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 강다은 담당 액션 수(4건)를 정확히 답변했고, 의미상 골든 답변과 동일하다. 도구 호출도 owner와 category를 정확히 지정해 PASS다.

---

### C-SC04 · structured_count · 일치

#### (정답)

**질문**
현재 CS-Bot의 리스크 분류 기록은 몇 건이야?

**답변**

> 동결된 csbot 메모리 스냅샷 기준 리스크 기록은 총 0건이다.

**참고 문항(출처)**
memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 0,
    "required_terms": [
      "0"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "risk",
        "operation": "count"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
현재 CS-Bot의 리스크 분류 기록은 몇 건이야?

**답변**

> CS-Bot의 리스크 분류 기록은 현재 기록에서 확인되지 않는다.

**참고 문항(반환 출처)**
반환 없음

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "risk",
      "operation": "count",
      "text_query": "CS-Bot 리스크"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2047.0 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [],
    "missing": [
      "0"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "risk",
              "operation": "count",
              "text_query": "CS-Bot 리스크"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "risk",
          "operation": "count"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 리스크 분류 기록이 없음을 명확히 밝혀 0건임을 의미상 충족한다. 수치 '0'이 직접 언급되진 않았으나, '기록에서 확인되지 않는다'는 표현은 동등하게 해석 가능하다. tool 호출도 category 'risk'에 대해 count를 수행해 의미를 보존했다.

---

### C-SC05 · structured_count · 일치

#### (정답)

**질문**
이지훈이 담당한 결정은 몇 건이야?

**답변**

> 동결된 csbot 메모리 스냅샷 기준 이지훈 담당 결정 기록은 총 15건이다.

**참고 문항(출처)**
memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "exact_count": 15,
    "required_terms": [
      "15"
    ],
    "type": "exact_count"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "decision",
        "operation": "count",
        "owner": "이지훈"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
이지훈이 담당한 결정은 몇 건이야?

**답변**

> 이지훈이 담당한 결정은 총 **15건**입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "decision",
      "operation": "count",
      "owner": "이지훈",
      "text_query": "이지훈"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2262.8 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "15"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "exact_count"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "decision",
              "operation": "count",
              "owner": "이지훈",
              "text_query": "이지훈"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "query_structured_memory",
        "required_args": {
          "category": "decision",
          "operation": "count",
          "owner": "이지훈"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 이지훈 담당 결정의 정확한 건수(15건)를 정확히 답변했고, 표현만 다를 뿐 의미는 동일하다. tool call 역시 owner와 category를 명확히 지정해 의미를 보존했다.

---

### C-SL01 · structured_list · 일치

#### (정답)

**질문**
박서연 담당 액션 목록을 전부 보여줘.

**답변**

> 동결된 스냅샷 기준 박서연 담당 액션 기록은 7건이다.
> - 현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 (6/5)
> - 박서연이 최신 정책 문서 기반으로 지식 베이스 전면 갱신을 진행하겠습니다. (마감 6/13)
> - 박서연이 semantic chunking 방식 조사 및 적용 방안 도출을 진행하겠습니다. (마감 6/13)
> - Semantic chunking 구현 및 하이브리드 검색 모듈 개발 (6/20까지)
> - LLM 모델 버전 업데이트 및 프롬프트 재설계 (6/20까지)
> - 박서연이 re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정을 진행하겠습니다 (~6/25까지).
> - 배포 후 24시간 LLM 응답 모니터링

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-09_진단결과_원인분석.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md, memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 7,
    "order_matters": false,
    "required_items": [
      "현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 (6/5)",
      "박서연이 최신 정책 문서 기반으로 지식 베이스 전면 갱신을 진행하겠습니다. (마감 6/13)",
      "박서연이 semantic chunking 방식 조사 및 적용 방안 도출을 진행하겠습니다. (마감 6/13)",
      "Semantic chunking 구현 및 하이브리드 검색 모듈 개발 (6/20까지)",
      "LLM 모델 버전 업데이트 및 프롬프트 재설계 (6/20까지)",
      "박서연이 re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정을 진행하겠습니다 (~6/25까지).",
      "배포 후 24시간 LLM 응답 모니터링"
    ],
    "required_owner": "박서연",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "박서연"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
박서연 담당 액션 목록을 전부 보여줘.

**답변**

> 박서연 담당 액션 목록은 다음과 같습니다.
>
> | 주제                     | 내용                                      | 날짜       | 완료 여부       |
> |------------------------|-----------------------------------------|----------|--------------|
> | chunk 분할 방식 조사          | semantic chunking 방식 조사 및 적용 방안 도출               | 2026-06-09 | 완료 여부 미확인  |
> | 지식 베이스 갱신             | 최신 정책 문서 기반으로 지식 베이스 전면 갱신                | 2026-06-09 | 완료 여부 미확인  |
> | re-ranking 모듈 통합          | re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정           | 2026-06-23 | 완료 여부 미확인  |
> | 모니터링                   | 배포 후 24시간 LLM 응답 모니터링                           | 2026-06-27 | 완료 여부 미확인  |
> | LLM 모델 업데이트           | LLM 모델 버전 업데이트 및 프롬프트 재설계 (6/20까지)          | 2026-06-16 | 완료 여부 미확인  |
> | RAG 파이프라인 점검          | 현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 (6/5)    | 2026-06-02 | 완료 여부 미확인  |
> | RAG 파이프라인 개선          | Semantic chunking 구현 및 하이브리드 검색 모듈 개발 (6/20까지) | 2026-06-16 | 완료 여부 미확인  |

**참고 문항(반환 출처)**
2026-06-09_진단결과_원인분석.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-27_최종QA_배포일정.md, 2026-06-16_개선방안_확정.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "박서연",
      "text_query": "박서연"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `8553.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 (6/5)",
      "Semantic chunking 구현 및 하이브리드 검색 모듈 개발 (6/20까지)",
      "LLM 모델 버전 업데이트 및 프롬프트 재설계 (6/20까지)",
      "배포 후 24시간 LLM 응답 모니터링"
    ],
    "missing": [
      "박서연이 최신 정책 문서 기반으로 지식 베이스 전면 갱신을 진행하겠습니다. (마감 6/13)",
      "박서연이 semantic chunking 방식 조사 및 적용 방안 도출을 진행하겠습니다. (마감 6/13)",
      "박서연이 re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정을 진행하겠습니다 (~6/25까지)."
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "박서연",
              "text_query": "박서연"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "박서연"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 박서연 담당 액션 7건을 모두 빠짐없이 포함하고 있으며, 각 항목의 내용도 골든 답변과 의미상 일치한다. 날짜 표기 방식이나 완료 여부 등 부가 정보가 추가됐으나, 요구된 핵심 목록에는 영향이 없다. 도구 호출도 owner와 category를 명확히 지정해 의미를 충족한다.

---

### C-SL02 · structured_list · 일치

#### (정답)

**질문**
강다은이 담당한 액션 목록을 알려줘.

**답변**

> 동결된 스냅샷 기준 강다은 담당 액션 기록은 4건이다.
> - 프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5)
> - 멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지)
> - 강다은이 회원/포인트 공개 문서 지식 베이스 추가를 진행하겠습니다 (~6/24까지).
> - 멀티턴 기능 설계 문서 작성

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md, memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 4,
    "order_matters": false,
    "required_items": [
      "프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5)",
      "멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지)",
      "강다은이 회원/포인트 공개 문서 지식 베이스 추가를 진행하겠습니다 (~6/24까지).",
      "멀티턴 기능 설계 문서 작성"
    ],
    "required_owner": "강다은",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "강다은"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
강다은이 담당한 액션 목록을 알려줘.

**답변**

> 강다은이 담당한 액션 목록은 다음과 같다.
>
> | 주제                     | 작업 내용                          | 날짜       | 완료 여부       |
> |------------------------|---------------------------------|----------|--------------|
> | 회원/포인트 문서 추가         | 회원/포인트 공개 문서 지식 베이스 추가 진행       | 2026-06-23 | 완료 여부 미확인  |
> | 기능 설계                  | 멀티턴 기능 설계 문서 작성               | 2026-06-27 | 완료 여부 미확인  |
> | 기능 조사                  | 멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지) | 2026-06-16 | 완료 여부 미확인  |
> | 프론트엔드 로그 분석           | 프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5) | 2026-06-02 | 완료 여부 미확인  |

**참고 문항(반환 출처)**
2026-06-23_QA결과검토_2차방향.md, 2026-06-27_최종QA_배포일정.md, 2026-06-16_개선방안_확정.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "강다은",
      "text_query": "강다은"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `5184.8 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5)",
      "멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지)",
      "멀티턴 기능 설계 문서 작성"
    ],
    "missing": [
      "강다은이 회원/포인트 공개 문서 지식 베이스 추가를 진행하겠습니다 (~6/24까지)."
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "강다은",
              "text_query": "강다은"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "강다은"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 골든 답변의 4개 액션을 모두 포함하고 있으며, 날짜 형식이나 완료 여부 표기 등 부가 정보가 추가되었으나 핵심 내용과 담당자, 액션 명칭이 모두 일치한다. 목록의 완전성과 의미가 유지되어 PASS로 판정한다. tool call 역시 owner와 category를 정확히 지정하여 PASS이다.

---

### C-SL03 · structured_list · 일치

#### (정답)

**질문**
윤재혁 담당 액션 목록을 모두 보여줘.

**답변**

> 동결된 스냅샷 기준 윤재혁 담당 액션 기록은 5건이다.
> - 자체 QA 환경에서 반품/환불 관련 질문 20개 테스트 및 오답률 측정 (6/5)
> - 윤재혁이 개선 후 재테스트를 위한 QA 케이스 30개 준비를 진행하겠습니다. (마감 6/13)
> - 30개 QA 케이스로 1차 개선 후 테스트 진행 (6/23까지)
> - 윤재혁이 re-ranking과 문서 보강 후 최종 QA 테스트 30개 케이스를 재실시하겠습니다 (~6/26까지).
> - 배포 후 3일 시점 QA 재측정

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-09_진단결과_원인분석.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md, memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 5,
    "order_matters": false,
    "required_items": [
      "자체 QA 환경에서 반품/환불 관련 질문 20개 테스트 및 오답률 측정 (6/5)",
      "윤재혁이 개선 후 재테스트를 위한 QA 케이스 30개 준비를 진행하겠습니다. (마감 6/13)",
      "30개 QA 케이스로 1차 개선 후 테스트 진행 (6/23까지)",
      "윤재혁이 re-ranking과 문서 보강 후 최종 QA 테스트 30개 케이스를 재실시하겠습니다 (~6/26까지).",
      "배포 후 3일 시점 QA 재측정"
    ],
    "required_owner": "윤재혁",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "윤재혁"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
윤재혁 담당 액션 목록을 모두 보여줘.

**답변**

> 윤재혁 담당 액션 목록은 다음과 같습니다.
>
> | 주제           | 내용                                               | 날짜       | 완료 여부    |
> |----------------|--------------------------------------------------|------------|-------------|
> | QA 케이스 준비  | 개선 후 재테스트를 위한 QA 케이스 30개 준비 진행 | 2026-06-09 | 완료 여부 미확인 |
> | 최종 QA 테스트  | re-ranking과 문서 보강 후 최종 QA 테스트 30개 케이스 재실시 (~6/26까지) | 2026-06-23 | 완료 여부 미확인 |
> | QA 재측정      | 배포 후 3일 시점 QA 재측정                        | 2026-06-27 | 완료 여부 미확인 |
> | QA 테스트      | 30개 QA 케이스로 1차 개선 후 테스트 진행 (6/23까지) | 2026-06-16 | 완료 여부 미확인 |
> | QA 테스트      | 자체 QA 환경에서 반품/환불 관련 질문 20개 테스트 및 오답률 측정 (6/5) | 2026-06-02 | 완료 여부 미확인 |

**참고 문항(반환 출처)**
2026-06-09_진단결과_원인분석.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-27_최종QA_배포일정.md, 2026-06-16_개선방안_확정.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "윤재혁",
      "text_query": "윤재혁"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `6019.2 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "자체 QA 환경에서 반품/환불 관련 질문 20개 테스트 및 오답률 측정 (6/5)",
      "30개 QA 케이스로 1차 개선 후 테스트 진행 (6/23까지)",
      "배포 후 3일 시점 QA 재측정"
    ],
    "missing": [
      "윤재혁이 개선 후 재테스트를 위한 QA 케이스 30개 준비를 진행하겠습니다. (마감 6/13)",
      "윤재혁이 re-ranking과 문서 보강 후 최종 QA 테스트 30개 케이스를 재실시하겠습니다 (~6/26까지)."
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "윤재혁",
              "text_query": "윤재혁"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "윤재혁"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

윤재혁 담당 액션 5건이 모두 빠짐없이 포함되어 있고, 각 항목의 내용도 골든 답변과 의미상 동일하다. 날짜 표기 방식이나 완료 여부 등 부가 정보가 추가됐으나, 요구된 핵심 목록에는 영향이 없다. tool 호출도 owner와 category를 정확히 지정해 PASS다.

---

### C-SL04 · structured_list · 일치

#### (정답)

**질문**
최민준이 담당한 액션 목록을 보여줘.

**답변**

> 동결된 스냅샷 기준 최민준 담당 액션 기록은 7건이다.
> - 서버 측 응답 로그 6개월치 추출 및 기초 통계 작성 (6/5)
> - 최민준이 청킹 방식 변경 후 전체 재임베딩 파이프라인 준비를 진행하겠습니다. (마감 6/16)
> - 전체 재임베딩 실행 및 하이브리드 검색 서버 연동 (6/21까지)
> - 최민준이 re-ranking 서버 연동 및 응답 시간 모니터링을 진행하겠습니다 (~6/25까지).
> - 스테이징 최종 확인
> - 1차 개선 프로덕션 배포
> - 서버 로그 모니터링 (1주일)

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-09_진단결과_원인분석.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md, memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 7,
    "order_matters": false,
    "required_items": [
      "서버 측 응답 로그 6개월치 추출 및 기초 통계 작성 (6/5)",
      "최민준이 청킹 방식 변경 후 전체 재임베딩 파이프라인 준비를 진행하겠습니다. (마감 6/16)",
      "전체 재임베딩 실행 및 하이브리드 검색 서버 연동 (6/21까지)",
      "최민준이 re-ranking 서버 연동 및 응답 시간 모니터링을 진행하겠습니다 (~6/25까지).",
      "스테이징 최종 확인",
      "1차 개선 프로덕션 배포",
      "서버 로그 모니터링 (1주일)"
    ],
    "required_owner": "최민준",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "최민준"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
최민준이 담당한 액션 목록을 보여줘.

**답변**

> 최민준이 담당한 액션 목록은 다음과 같다:
>
> | 주제                     | 액션 내용                                   | 날짜       | 완료 여부       |
> |------------------------|----------------------------------------|----------|--------------|
> | re-ranking 서버 연동        | re-ranking 서버 연동 및 응답 시간 모니터링 진행          | 2026-06-23 | 완료 여부 미확인  |
> | 재임베딩 파이프라인 준비     | 청킹 방식 변경 후 전체 재임베딩 파이프라인 준비 진행       | 2026-06-09 | 완료 여부 미확인  |
> | 모니터링                  | 서버 로그 모니터링 (1주일)                      | 2026-06-27 | 완료 여부 미확인  |
> | 배포 준비                 | 스테이징 최종 확인                            | 2026-06-27 | 완료 여부 미확인  |
> | 배포 실행                 | 1차 개선 프로덕션 배포                          | 2026-06-27 | 완료 여부 미확인  |
> | 응답 로그 분석              | 서버 측 응답 로그 6개월치 추출 및 기초 통계 작성           | 2026-06-02 | 완료 여부 미확인  |
> | RAG 파이프라인 개선         | 전체 재임베딩 실행 및 하이브리드 검색 서버 연동             | 2026-06-16 | 완료 여부 미확인  |

**참고 문항(반환 출처)**
2026-06-23_QA결과검토_2차방향.md, 2026-06-09_진단결과_원인분석.md, 2026-06-27_최종QA_배포일정.md, 2026-06-02_유지보수요청_초기대응.md, 2026-06-16_개선방안_확정.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "owner": "최민준",
      "text_query": "최민준"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `7909.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "스테이징 최종 확인",
      "1차 개선 프로덕션 배포",
      "서버 로그 모니터링 (1주일)"
    ],
    "missing": [
      "서버 측 응답 로그 6개월치 추출 및 기초 통계 작성 (6/5)",
      "최민준이 청킹 방식 변경 후 전체 재임베딩 파이프라인 준비를 진행하겠습니다. (마감 6/16)",
      "전체 재임베딩 실행 및 하이브리드 검색 서버 연동 (6/21까지)",
      "최민준이 re-ranking 서버 연동 및 응답 시간 모니터링을 진행하겠습니다 (~6/25까지)."
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "owner": "최민준",
              "text_query": "최민준"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "최민준"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 골든 답변의 7개 액션을 모두 의미상 정확히 포함하고 있다. 날짜 표기가 다르지만, 액션의 내용과 담당자가 일치하며, 추가적 허위 정보나 누락이 없다. 테이블 형식으로 표현했으나 요구된 모든 항목을 충족한다.

---

### C-SL05 · structured_list · 일치

#### (정답)

**질문**
강다은이 담당한 이슈 목록을 알려줘.

**답변**

> 동결된 스냅샷 기준 강다은 담당 이슈 기록은 1건이다.
> - 멀티턴 맥락 유지 기능: 강다은이 공수 조사 후 다음 회의에서 논의

**참고 문항(출처)**
sources/csbot/2026-06-16_개선방안_확정.md, memory_snapshots/csbot.json

**기대 도구** `query_structured_memory` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "expected_total": 1,
    "order_matters": false,
    "required_items": [
      "멀티턴 맥락 유지 기능: 강다은이 공수 조사 후 다음 회의에서 논의"
    ],
    "required_owner": "강다은",
    "type": "unordered_complete_list"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "issue",
        "limit": 8,
        "operation": "list",
        "owner": "강다은"
      },
      "name": "query_structured_memory"
    }
  ]
}
```

#### (실제)

**질문**
강다은이 담당한 이슈 목록을 알려줘.

**답변**

> 강다은이 담당한 이슈 목록은 "멀티턴 맥락 유지 기능"이며, 강다은이 공수 조사 후 다음 회의에서 논의하기로 되어 있습니다.

**참고 문항(반환 출처)**
2026-06-16_개선방안_확정.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "issue",
      "operation": "list",
      "owner": "강다은",
      "text_query": "강다은"
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `2577.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [],
    "missing": [
      "멀티턴 맥락 유지 기능: 강다은이 공수 조사 후 다음 회의에서 논의"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "unordered_complete_list"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "query_structured_memory"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "query_structured_memory"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "issue",
              "operation": "list",
              "owner": "강다은",
              "text_query": "강다은"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "issue",
          "limit": 8,
          "operation": "list",
          "owner": "강다은"
        }
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

실제 답변은 골든 답변의 모든 핵심 사실(이슈명, 담당자, 진행상황)을 정확히 포함하고 있다. 목록이 1건임도 명확히 드러난다. 도구 호출도 owner와 category를 정확히 지정했다.

---

### C-OV01 · overview · 일치

#### (정답)

**질문**
CS-Bot 유지보수 프로젝트 전체 현황을 브리핑해줘.

**답변**

> 지식 베이스·semantic chunking·하이브리드 검색·re-ranking 개선을 진행했고 1차 배포는 6월 30일로 정했다. 배포 후 1주 모니터링과 3일 시점 QA 재측정, 7월 3일 2차 개선 회의가 계획돼 있다.

**참고 문항(출처)**
overview_snapshots/csbot.json, memory_snapshots/csbot.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "min_required_facts": 5,
    "required_facts": [
      "6월 30일",
      "re-ranking",
      "1주일 모니터링",
      "3일 시점 QA",
      "7월 3일"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
CS-Bot 유지보수 프로젝트 전체 현황을 브리핑해줘.

**답변**

> CS-Bot 유지보수 프로젝트는 최근 3개월치 질의-응답 로그와 최신 정책 문서 요청을 공식 진행 중이며, 지식 베이스를 최신 정책 기준으로 semantic chunking 방식으로 전면 갱신하기로 결정되어 있습니다. LLM 모델은 최신 버전으로 업데이트하고, RAG 파이프라인에 하이브리드 검색과 re-ranking 도입을 우선 적용하며, 멀티턴 맥락 유지 기능은 2차 배포로 분리했습니다. 1차 개선 배포는 6월 30일로 확정되었고, 배포 후 1주일간 집중 모니터링과 3일 시점 QA 재측정을 계획 중입니다. 주요 이슈로는 고객사의 데이터 공유 동의 여부, 유지보수 범위 및 비용, 검색 알고리즘 개선 수준, 멀티턴 기능 도입 여부, 운영 비용 조정 등이 남아있으며, 2차 개선 계획 수립을 위한 별도 회의는 7월 3일에 예정되어 있습니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `5891.5 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": false
      },
      {
        "category": "action",
        "count": 30,
        "matched": false
      },
      {
        "category": "issue",
        "count": 11,
        "matched": false
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "6월 30일",
      "re-ranking",
      "3일 시점 QA",
      "7월 3일"
    ],
    "missing": [
      "1주일 모니터링"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `N/A`

요구된 핵심 일정(6월 30일, 7월 3일), 주요 기능(re-ranking), 배포 후 1주 모니터링, 3일 시점 QA 등 모든 필수 사실이 정확히 포함되어 있다. 추가로 프로젝트의 세부 진행 상황과 이슈까지 상세히 설명해 골든 답변보다 정보가 더 풍부하지만, 핵심 요구를 모두 충족하므로 PASS이다.

---

### C-OV02 · overview · 부분일치

#### (정답)

**질문**
카테고리별 기록 수와 현재 대표 액션을 같이 정리해줘.

**답변**

> 동결 스냅샷의 활성 기록은 결정 15건, 액션 30건, 이슈 11건, 리스크 0건이다. 대표 액션에는 스테이징 확인, 프로덕션 배포, LLM 응답·서버 로그 모니터링, QA 재측정, 계약 연장 협의가 있다.

**참고 문항(출처)**
overview_snapshots/csbot.json, memory_snapshots/csbot.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "min_required_facts": 5,
    "required_facts": [
      "결정 15",
      "액션 30",
      "이슈 11",
      "리스크 0",
      "프로덕션 배포"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 현재 대표 액션을 같이 정리해줘.

**답변**

> **카테고리별 기록 수는 결정 15건, 액션 30건, 이슈 11건이며, 현재 대표 액션은 모두 상태가 'unknown'인 다음 5건입니다.**
>
> | 액션 내용                     | 담당자   | 상태      |
> |----------------------------|--------|---------|
> | 멀티턴 기능 설계 문서 작성          | 강다은   | unknown |
> | 계약 연장 협의 착수               | 이지훈   | unknown |
> | 고객사에 배포 완료 안내 및 피드백 요청 | 이지훈   | unknown |
> | 배포 후 3일 시점 QA 재측정          | 윤재혁   | unknown |
> | 서버 로그 모니터링 (1주일)          | 최민준   | unknown |

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `3835.9 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": true
      },
      {
        "category": "action",
        "count": 30,
        "matched": true
      },
      {
        "category": "issue",
        "count": 11,
        "matched": true
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "결정 15",
      "액션 30",
      "이슈 11"
    ],
    "missing": [
      "리스크 0",
      "프로덕션 배포"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `N/A`

결정 15·액션 30·이슈 11과 여러 유효 대표 액션은 맞지만 리스크 0건과 계약이 요구한 프로덕션 배포를 빠뜨렸다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "core_facts_missing": [
    "리스크 0건",
    "프로덕션 배포"
  ],
  "failure_codes": [
    "MISSING_FACT"
  ]
}
```

---

### C-OV03 · overview · 일치

#### (정답)

**질문**
경영진용으로 CS-Bot 개선 상황을 한눈에 요약해줘.

**답변**

> 최신 정책 기준 지식 베이스와 semantic chunking, 하이브리드 검색, re-ranking을 핵심 개선 방향으로 추진했다. 멀티턴은 2차 배포로 분리했고 6월 30일 1차 배포 후 모니터링을 계획했다.

**참고 문항(출처)**
overview_snapshots/csbot.json, memory_snapshots/csbot.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "min_required_facts": 6,
    "required_facts": [
      "지식 베이스",
      "semantic chunking",
      "하이브리드",
      "re-ranking",
      "멀티턴 2차",
      "6월 30일"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
경영진용으로 CS-Bot 개선 상황을 한눈에 요약해줘.

**답변**

> CS-Bot 개선 상황은 **1차 개선 배포가 6월 30일로 확정되었고, 이후 1주일간 집중 모니터링과 3일 시점 QA 재측정이 예정되어 있다**는 점이 핵심입니다.
>
> - 고객사로부터 최근 3개월치 질의-응답 로그와 최신 정책 문서 요청을 공식 진행 중이며, 지식 베이스를 최신 정책 기준으로 전면 갱신한다.
> - LLM 모델은 최신 버전으로 업데이트하고, RAG 파이프라인에 하이브리드 검색과 re-ranking 기능을 우선 적용한다.
> - 멀티턴 맥락 유지 기능은 2차 배포로 분리하여 추후 도입할 계획이다.
> - 1차 배포 후 1주일간 서버 로그 모니터링과 3일 시점 QA 재측정 작업이 진행된다.
> - 주요 이슈로는 고객사 데이터 공유 동의, 유지보수 범위 및 비용, 검색 알고리즘 개선 수준, 멀티턴 기능 도입 여부, 운영 비용 조정 등이 남아있다.
> - 2차 개선 계획 수립을 위한 별도 회의는 7월 3일에 예정되어 있다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md

**실제 도구** `get_project_overview` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  }
]
```

**API** `200` · **응답시간** `4524.8 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": false
      },
      {
        "category": "action",
        "count": 30,
        "matched": false
      },
      {
        "category": "issue",
        "count": 11,
        "matched": false
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "지식 베이스",
      "하이브리드",
      "re-ranking",
      "6월 30일"
    ],
    "missing": [
      "semantic chunking",
      "멀티턴 2차"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `0.98` · semantic 검색 인자 `N/A`

실제 답변은 경영진이 한눈에 파악할 수 있도록 1차 배포 일정(6월 30일), 지식 베이스 최신화, 하이브리드 검색 및 re-ranking 적용, 멀티턴 기능의 2차 배포 분리 등 핵심 개선 방향을 모두 명확히 요약했다. 'semantic chunking'이 직접 언급되지는 않았으나, RAG 파이프라인 개선과 최신 정책 기준 지식 베이스 갱신 등으로 사실상 포함된 맥락을 전달하고 있다. 요구된 6개 핵심 사실 중 5개가 명확히 포함되어 있고, 전체 맥락상 경영진 요약으로 충분하다. 경미한 누락이 있으나, 중심 결론과 주요 개선 방향이 모두 충족되어 PASS로 판단한다.

```json
{
  "core_facts_missing": [
    "semantic chunking"
  ]
}
```

---

### C-OV04 · overview · 불일치

#### (정답)

**질문**
결정·액션·이슈 중심으로 현재 상태와 남은 쟁점을 정리해줘.

**답변**

> 활성 기록은 결정 15, 액션 30, 이슈 11건이며 risk 분류 행은 없다. 고객사 데이터 공유 동의, 유지보수 범위와 비용, 검색 개선 수준, 운영 비용 조정이 남은 쟁점이고 배포·모니터링·QA 재측정 액션이 예정돼 있다.

**참고 문항(출처)**
overview_snapshots/csbot.json, memory_snapshots/csbot.json

**기대 도구** `get_project_overview` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "min_required_facts": 7,
    "required_facts": [
      "결정 15",
      "액션 30",
      "이슈 11",
      "데이터 공유",
      "유지보수 범위",
      "운영 비용",
      "QA 재측정"
    ],
    "type": "overview_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    }
  ]
}
```

#### (실제)

**질문**
결정·액션·이슈 중심으로 현재 상태와 남은 쟁점을 정리해줘.

**답변**

> 현재 상태와 남은 쟁점은 다음과 같이 정리할 수 있습니다.
>
> **결정 사항 (Decision) 주요 현황:**
> - 1차 개선 배포 일정은 2026년 6월 30일 오후 2시로 확정되었고, 스테이징 최종 확인은 6월 30일 오전 중 완료 예정입니다.
> - 배포 후 1주일간 집중 모니터링을 진행하며, 배포 후 3일 시점에 QA 재측정을 실시하기로 했습니다.
> - 멀티턴 맥락 유지 기능은 2차 배포 항목으로 분리하여 다음 스프린트에 포함하기로 결정했습니다.
> - re-ranking(cross-encoder 기반)을 정식 도입하기로 했으며, LLM 모델은 최신 버전으로 업데이트하기로 했습니다.
> - 파인튜닝 도입은 이번 유지보수에서 제외하고 추후 2차 유지보수 또는 계약 연장 시 검토하기로 했습니다.
> - 프롬프트는 전면 재설계하기로 결정했습니다.
>
> **액션 항목 (Action) 주요 진행 상황:**
> | 작업명                     | 담당자   | 날짜       | 완료 여부       |
> |--------------------------|--------|----------|--------------|
> | 멀티턴 기능 설계 문서 작성       | 강다은   | 2026-06-27 | 미확인         |
> | 계약 연장 협의 착수             | 이지훈   | 2026-06-27 | 미확인         |
> | 고객사에 배포 완료 안내 및 피드백 요청 | 이지훈   | 2026-06-27 | 미확인         |
> | 배포 후 3일 시점 QA 재측정       | 윤재혁   | 2026-06-27 | 미확인         |
> | 서버 로그 모니터링 (1주일)       | 최민준   | 2026-06-27 | 미확인         |
> | 배포 후 24시간 LLM 응답 모니터링  | 박서연   | 2026-06-27 | 미확인         |
> | 1차 개선 프로덕션 배포           | 최민준   | 2026-06-27 | 미확인         |
> | 스테이징 최종 확인              | 최민준   | 2026-06-27 | 미확인         |
> | 고객사 사전 보고 일정 협의        | 이지훈   | 2026-06-23 | 미확인         |
> | re-ranking과 문서 보강 후 최종 QA 테스트 | 윤재혁   | 2026-06-23 | 미확인         |
>
> **남은 쟁점 (Issue):**
> - 구조화 기록에서 별도의 열린 이슈는 확인되지 않으나, 원문 맥락에서 추가 확인 필요할 수 있습니다.
>
> 요약하면, 1차 배포가 임박했고 배포 후 모니터링 및 QA 재측정이 예정되어 있으며, 멀티턴 기능 등 일부 기능은 2차 배포로 이관되어 현재 1차 배포 품질과 일정에 집중하는 상태입니다. 계약 연장 협의와 고객사 커뮤니케이션도 진행 중입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md

**실제 도구** `query_structured_memory` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "decision",
      "completion_status": null,
      "limit": 10,
      "operation": "list",
      "text_query": ""
    },
    "name": "query_structured_memory"
  },
  {
    "args": {
      "category": "action",
      "completion_status": null,
      "limit": 10,
      "operation": "list",
      "text_query": ""
    },
    "name": "query_structured_memory"
  },
  {
    "args": {
      "category": "issue",
      "completion_status": "open",
      "limit": 10,
      "operation": "list",
      "text_query": ""
    },
    "name": "query_structured_memory"
  }
]
```

**API** `200` · **응답시간** `11882.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": false
      },
      {
        "category": "action",
        "count": 30,
        "matched": false
      },
      {
        "category": "issue",
        "count": 11,
        "matched": false
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "QA 재측정"
    ],
    "missing": [
      "결정 15",
      "액션 30",
      "이슈 11",
      "데이터 공유",
      "유지보수 범위",
      "운영 비용"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "overview_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": false,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": false
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory"
    ],
    "allowed_tools": [
      "get_project_overview"
    ],
    "effective_args_pass": false,
    "exact_args_pass": false,
    "extra_tool_calls": 2,
    "max_tool_rounds": 1,
    "required_tools": [
      "get_project_overview"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": false,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "get_project_overview",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": false
  }
}
```

#### 최종 답변 판정

**불일치** · 신뢰도 `0.99` · semantic 검색 인자 `N/A`

overview 대신 category별 구조화 목록을 호출했고 issue에 action 전용 completion_status=open을 적용했다. 그 결과 핵심 건수와 남은 쟁점을 누락하고 이슈가 없다는 잘못된 결론을 냈다.

_동결 근거 재검토 적용: 자동 판정 FAIL → 최종 판정 FAIL_

```json
{
  "contradictions": [
    "이슈 11건이 있는데 completion_status=open 필터 결과를 근거로 열린 이슈가 없다고 단정"
  ],
  "core_facts_missing": [
    "결정 15·액션 30·이슈 11",
    "데이터 공유",
    "유지보수 범위와 비용",
    "운영 비용"
  ],
  "failure_codes": [
    "MISSING_FACT",
    "WRONG_FACT"
  ]
}
```

---

### C-MX01 · mixed_tools · 부분일치

#### (정답)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 프로젝트 전체 현황, 그리고 최종 전체 정답률을 함께 알려줘.

**답변**

> 활성 기록은 결정 15건, 액션 30건, 이슈 11건, 리스크 0건이다. 스테이징 확인, 프로덕션 배포, 배포 후 모니터링과 QA 재측정이 대표 액션으로 기록돼 있다. 6월 27일 최종 전체 정답률은 87%로 개선 전 55%보다 32%p 상승했다.

**참고 문항(출처)**
overview_snapshots/csbot.json, sources/csbot/2026-06-27_최종QA_배포일정.md

**기대 도구** `get_project_overview, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "required_terms": [
      "프로덕션 배포",
      "87%",
      "55%",
      "32%p"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    },
    {
      "args_semantics": "6/27 최종 전체 정답률",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 프로젝트 전체 현황, 그리고 최종 전체 정답률을 함께 알려줘.

**답변**

> 프로젝트 전체 현황은 카테고리별 기록 수가 결정 15건, 액션 30건, 이슈 11건이며, 대표 액션으로는 "배포 후 3일 시점 QA 재측정"(윤재혁 담당), "스테이징 최종 확인"(최민준 담당), "계약 연장 협의 착수"(이지훈 담당) 등이 있습니다. 최종 전체 정답률은 87%로 크게 개선되었습니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-02_유지보수요청_초기대응.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-09_진단결과_원인분석.md, 2026-06-16_개선방안_확정.md

**실제 도구** `get_project_overview, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  },
  {
    "args": {
      "query": "전체 정답률"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `4258.7 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": true
      },
      {
        "category": "action",
        "count": 30,
        "matched": true
      },
      {
        "category": "issue",
        "count": 11,
        "matched": true
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "87%"
    ],
    "missing": [
      "프로덕션 배포",
      "55%",
      "32%p"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      },
      {
        "actual_candidates": [
          {
            "args": {
              "query": "전체 정답률"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "6/27 최종 전체 정답률",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `FAIL`

87%와 일부 현황은 맞지만 55%, 32%p, 리스크 0과 프로덕션 배포를 누락했다. 검색어도 6/27·최종 한정어를 잃었지만 실제로 정답 청크는 회수했으므로 최종 합성 누락도 함께 발생했다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "core_facts_missing": [
    "리스크 0건",
    "프로덕션 배포",
    "개선 전 55%",
    "32%p 상승"
  ],
  "failure_codes": [
    "MISSING_FACT",
    "SEMANTIC_QUERY_MISS"
  ]
}
```

---

### C-MX02 · mixed_tools · 부분일치

#### (정답)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 전체 상태, 그리고 개선 전 fallback 비율을 같이 요약해줘.

**답변**

> 활성 기록은 결정 15건, 액션 30건, 이슈 11건, 리스크 0건이다. 프로덕션 배포, 서버 로그 모니터링, QA 재측정이 대표 액션으로 기록돼 있다. 개선 전 fallback은 전체 질의의 18%였고 반품·교환 질문에서는 31%였다.

**참고 문항(출처)**
overview_snapshots/csbot.json, sources/csbot/2026-06-09_진단결과_원인분석.md

**기대 도구** `get_project_overview, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "category_counts": {
      "action": 30,
      "decision": 15,
      "issue": 11,
      "risk": 0
    },
    "required_terms": [
      "서버 로그 모니터링",
      "18%",
      "31%"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_required": {},
      "name": "get_project_overview"
    },
    {
      "args_semantics": "개선 전 fallback 전체와 반품·교환 비율",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
카테고리별 기록 수와 대표 액션을 포함한 전체 상태, 그리고 개선 전 fallback 비율을 같이 요약해줘.

**답변**

> 전체 상태 요약은 다음과 같으며, 개선 전 fallback 비율은 18%로 확인된다.
>
> - 카테고리별 기록 수:
>   - 결정(decision): 15건
>   - 액션(action): 30건
>   - 이슈(issue): 11건
>
> - 대표 액션 예시:
>   - 박서연: re-ranking 모듈 정식 통합 및 최종 프롬프트 버전 확정 (마감 6/25)
>   - 최민준: re-ranking 서버 연동 및 응답 시간 모니터링 (마감 6/25)
>   - 강다은: 회원/포인트 공개 문서 지식 베이스 추가 (마감 6/24)
>   - 이지훈: 그린커머스에 내부 포인트 문서 추가 요청 (마감 6/24)
>   - 윤재혁: re-ranking + 문서 보강 후 최종 QA 테스트 30개 재실시 (마감 6/26)
>
> - 개선 전 fallback 비율:
>   - 전체 fallback 응답 비율은 18%
>   - 반품 및 교환 관련 키워드 질문의 fallback 비율은 31%로 높음
>
> - 프로젝트 전반 현황:
>   - 1차 개선 배포는 6월 30일 예정이며, 배포 후 1주일간 집중 모니터링과 3일 시점 QA 재측정을 실시할 계획
>   - 주요 이슈로는 계약 범위 및 비용, 검색 알고리즘 개선 수준, 멀티턴 기능 도입 여부 등이 남아 있음
>   - 2차 개선 계획 수립을 위한 별도 회의는 7월 3일 예정
>
> **요약: 현재 프로젝트는 1차 개선 배포 직전 상태이며, fallback 비율은 개선 전 18%로 파악되고, 30건의 액션이 진행 중이다.**

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-02_유지보수요청_초기대응.md, 2026-06-09_진단결과_원인분석.md, 2026-06-16_개선방안_확정.md, 2026-06-23_QA결과검토_2차방향.md

**실제 도구** `get_project_overview, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {},
    "name": "get_project_overview"
  },
  {
    "args": {
      "query": "fallback 비율 개선 전"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `8078.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [
      {
        "category": "decision",
        "count": 15,
        "matched": false
      },
      {
        "category": "action",
        "count": 30,
        "matched": false
      },
      {
        "category": "issue",
        "count": 11,
        "matched": false
      },
      {
        "category": "risk",
        "count": 0,
        "matched": false
      }
    ],
    "matched": [
      "18%",
      "31%"
    ],
    "missing": [
      "서버 로그 모니터링"
    ],
    "must_abstain": false,
    "strict_text_pass": false,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "get_project_overview",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {},
            "name": "get_project_overview"
          }
        ],
        "args_semantics": null,
        "matched_required_args": true,
        "name": "get_project_overview",
        "required_args": {}
      },
      {
        "actual_candidates": [
          {
            "args": {
              "query": "fallback 비율 개선 전"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "개선 전 fallback 전체와 반품·교환 비율",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `PASS`

18%·31%와 결정 15·액션 30·이슈 11은 정확하다. 리스크 0과 요구된 대표 액션 일부를 빠뜨렸고 unknown 상태를 진행 중으로 단정했다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "contradictions": [
    "완료 여부 unknown인 액션 30건을 진행 중이라고 표현"
  ],
  "core_facts_missing": [
    "리스크 0건",
    "프로덕션 배포",
    "서버 로그 모니터링의 명시적 대표 액션"
  ],
  "failure_codes": [
    "MISSING_FACT",
    "UNSUPPORTED_CLAIM"
  ]
}
```

---

### C-MX03 · mixed_tools · 일치

#### (정답)

**질문**
박서연 담당 액션을 모두 보여주고 re-ranking을 정식 도입한 수치 근거도 설명해줘.

**답변**

> 박서연 담당 액션은 7건이다:
> - 현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 (6/5)
> - 박서연이 최신 정책 문서 기반으로 지식 베이스 전면 갱신을 진행하겠습니다. (마감 6/13)
> - 박서연이 semantic chunking 방식 조사 및 적용 방안 도출을 진행하겠습니다. (마감 6/13)
> - Semantic chunking 구현 및 하이브리드 검색 모듈 개발 (6/20까지)
> - LLM 모델 버전 업데이트 및 프롬프트 재설계 (6/20까지)
> - 박서연이 re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정을 진행하겠습니다 (~6/25까지).
> - 배포 후 24시간 LLM 응답 모니터링
> re-ranking 예비 테스트에서 환불 정확도가 75%에서 88%로 13%p 올랐고 지연 증가는 0.6초여서 정식 도입했다.

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-09_진단결과_원인분석.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md

**기대 도구** `query_structured_memory, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "7",
      "박서연",
      "75%",
      "88%",
      "13%p",
      "0.6초"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "박서연"
      },
      "name": "query_structured_memory"
    },
    {
      "args_semantics": "re-ranking 정식 도입 수치 근거",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
박서연 담당 액션을 모두 보여주고 re-ranking을 정식 도입한 수치 근거도 설명해줘.

**답변**

> 박서연 담당 액션은 다음과 같고, re-ranking 정식 도입 수치 근거는 예비 테스트에서 환불 영역 정확도가 75%에서 88%로 13%p 향상되었고, 응답 지연은 평균 0.6초 증가해 허용 가능한 수준으로 확인되어 정식 도입 결정되었습니다.
>
> | 담당자 | 액션 내용 | 마감일 | 출처 |
> |--------|------------|--------|-------|
> | 박서연 | semantic chunking 방식 조사 및 적용 방안 도출 | 6/13 | 2026-06-09_진단결과_원인분석.md |
> | 박서연 | 최신 정책 문서 기반 지식 베이스 전면 갱신 | 6/13 | 2026-06-09_진단결과_원인분석.md |
> | 박서연 | re-ranking 모듈 정식 통합과 최종 프롬프트 버전 확정 | 6/25 | 2026-06-23_QA결과검토_2차방향.md |
> | 박서연 | 배포 후 24시간 LLM 응답 모니터링 | - | 2026-06-27_최종QA_배포일정.md |
> | 박서연 | LLM 모델 버전 업데이트 및 프롬프트 재설계 | 6/20 | 2026-06-16_개선방안_확정.md |
> | 박서연 | 현재 RAG 파이프라인 구성 문서화 및 모델 버전 현황 정리 | 6/5 | 2026-06-02_유지보수요청_초기대응.md |
> | 박서연 | Semantic chunking 구현 및 하이브리드 검색 모듈 개발 | 6/20 | 2026-06-16_개선방안_확정.md |
>
> **re-ranking 정식 도입 수치 근거:**
> - 환불 영역 정확도 75% → 88% (13%p 향상)
> - 응답 시간 증가 평균 0.6초 (기존 2.3초 → 약 2.9초), 허용 가능한 수준
> - 예비 테스트 결과를 바탕으로 2026-06-23에 정식 도입 결정됨 (담당: 이지훈)

**참고 문항(반환 출처)**
2026-06-09_진단결과_원인분석.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-27_최종QA_배포일정.md, 2026-06-16_개선방안_확정.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "text_query": "박서연"
    },
    "name": "query_structured_memory"
  },
  {
    "args": {
      "query": "re-ranking 정식 도입 수치 근거"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `14537.3 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "7",
      "박서연",
      "75%",
      "88%",
      "13%p",
      "0.6초"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": false,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "effective_args_pass": false,
    "exact_args_pass": false,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "text_query": "박서연"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "박서연"
        }
      },
      {
        "actual_candidates": [
          {
            "args": {
              "query": "re-ranking 정식 도입 수치 근거"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "re-ranking 정식 도입 수치 근거",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

박서연 담당 액션 7건을 모두 빠짐없이 표로 제시했고, re-ranking 정식 도입의 수치 근거(정확도 75%→88%, 13%p 향상, 지연 0.6초 증가)도 모두 포함되어 있다. 추가로 도입 결정일과 담당자 정보가 더해졌으나, 이는 본질적 요구사항을 벗어나지 않는다. 도구 호출도 의미를 잘 보존했다.

---

### C-MX04 · mixed_tools · 일치

#### (정답)

**질문**
강다은 담당 액션을 모두 보여주고 멀티턴 기능이 2차 배포로 간 이유도 설명해줘.

**답변**

> 강다은 담당 액션은 4건이다:
> - 프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5)
> - 멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지)
> - 강다은이 회원/포인트 공개 문서 지식 베이스 추가를 진행하겠습니다 (~6/24까지).
> - 멀티턴 기능 설계 문서 작성
> 멀티턴은 1차 일정이 촉박하고 고객사의 명시 요구가 아니며 무리한 포함이 품질 위험을 만들 수 있어 2차 배포로 분리했다.

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md

**기대 도구** `query_structured_memory, search_project_evidence` · **최대 도구 라운드** `2`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "4",
      "강다은",
      "2차",
      "일정",
      "품질"
    ],
    "type": "required_facts"
  },
  "tool_calls": [
    {
      "args_ignored": [
        "text_query"
      ],
      "args_required": {
        "category": "action",
        "limit": 8,
        "operation": "list",
        "owner": "강다은"
      },
      "name": "query_structured_memory"
    },
    {
      "args_semantics": "멀티턴 2차 배포 분리 이유",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
강다은 담당 액션을 모두 보여주고 멀티턴 기능이 2차 배포로 간 이유도 설명해줘.

**답변**

> **강다은 담당 액션은 회원/포인트 공개 문서 지식 베이스 추가, 멀티턴 기능 설계 문서 작성, 멀티턴 맥락 유지 기능 구현 가능성 조사, 프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 등이며, 멀티턴 기능이 2차 배포로 간 이유는 1차 배포 일정이 타이트하고 고객사 명시 요청이 아닌 추가 개선 항목이라 무리하게 포함 시 배포 품질 리스크가 있기 때문입니다.**
>
> 근거 상세:
> - 강다은 담당 액션
>   - 회원/포인트 공개 문서 지식 베이스 추가 (6/24까지)
>   - 멀티턴 기능 설계 문서 작성 (6/27까지)
>   - 멀티턴 맥락 유지 기능 구현 가능성 조사 (6/20까지)
>   - 프론트엔드 입력 로그 분석 및 사용자 질문 패턴 정리 (6/5까지)
> - 멀티턴 기능 2차 배포 이유
>   - 1차 배포 일정이 매우 타이트함
>   - 멀티턴 기능은 고객사에서 명시적으로 요청한 기능이 아님
>   - 무리하게 1차 배포에 포함 시 품질 리스크가 발생할 우려 있음
>   - 따라서 2차 배포 항목으로 분리하여 다음 스프린트에 포함하기로 결정됨 (이지훈 결정, 6/23)

**참고 문항(반환 출처)**
2026-06-23_QA결과검토_2차방향.md, 2026-06-27_최종QA_배포일정.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md, 2026-06-02_유지보수요청_초기대응.md

**실제 도구** `query_structured_memory, search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "category": "action",
      "operation": "list",
      "text_query": "강다은"
    },
    "name": "query_structured_memory"
  },
  {
    "args": {
      "query": "멀티턴 기능 2차 배포 이유"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `8563.4 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "4",
      "강다은",
      "2차",
      "일정",
      "품질"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "required_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": false,
      "serialized_pass": false
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "allowed_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "effective_args_pass": false,
    "exact_args_pass": false,
    "extra_tool_calls": 0,
    "max_tool_rounds": 2,
    "required_tools": [
      "query_structured_memory",
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": false,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": false,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "category": "action",
              "operation": "list",
              "text_query": "강다은"
            },
            "name": "query_structured_memory"
          }
        ],
        "args_semantics": null,
        "matched_required_args": false,
        "name": "query_structured_memory",
        "required_args": {
          "category": "action",
          "limit": 8,
          "operation": "list",
          "owner": "강다은"
        }
      },
      {
        "actual_candidates": [
          {
            "args": {
              "query": "멀티턴 기능 2차 배포 이유"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "멀티턴 2차 배포 분리 이유",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

강다은 담당 액션 4건을 모두 구체적으로 명시했고, 멀티턴 기능이 2차 배포로 간 이유도 일정, 품질, 고객사 요구 아님 등 핵심 사유를 모두 포함해 설명했다. 추가로 결정 주체와 날짜까지 근거를 보강했으나, 이는 골든 답변의 범위를 벗어나지 않고 사실관계를 강화하는 수준이다. 도구 호출 쿼리도 의미를 잘 보존했다.

---

### C-SE01 · semantic_boundary · 일치

#### (정답)

**질문**
최종 전체 정답률과 개선 전 대비 상승 폭은 얼마야?

**답변**

> 6월 27일 기준 최종 전체 정답률은 87%이고, 개선 전 55%보다 32%p 상승했다.

**참고 문항(출처)**
sources/csbot/2026-06-27_최종QA_배포일정.md

**기대 도구** `search_project_evidence` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "required_terms": [
      "87%",
      "55%",
      "32%p"
    ],
    "type": "semantic_facts"
  },
  "tool_calls": [
    {
      "args_semantics": "질문 전체 의미를 보존",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
최종 전체 정답률과 개선 전 대비 상승 폭은 얼마야?

**답변**

> 최종 전체 정답률은 **87%**이며, 개선 전 대비 상승 폭은 **32%p (55% → 87%)**입니다.
>
> 근거:
> - 1차 개선 전 전체 정답률은 55%였습니다.
> - 1차 개선 후 80%로 상승했고, 최종 QA 테스트 결과 87%까지 올랐습니다.
> - 따라서 최종 개선 폭은 87% - 55% = 32%p입니다.

**참고 문항(반환 출처)**
2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-16_개선방안_확정.md, 2026-06-09_진단결과_원인분석.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "alternate_queries": [
        "전체 정답률",
        "최종 정답률",
        "정답률 최종 수치"
      ],
      "query": "최종 전체 정답률"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `5983.5 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "87%",
      "55%",
      "32%p"
    ],
    "missing": [],
    "must_abstain": false,
    "strict_text_pass": true,
    "type": "semantic_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": true
    },
    "overall": {
      "pass": true
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "alternate_queries": [
                "전체 정답률",
                "최종 정답률",
                "정답률 최종 수치"
              ],
              "query": "최종 전체 정답률"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "질문 전체 의미를 보존",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**일치** · 신뢰도 `1.0` · semantic 검색 인자 `PASS`

질문이 요구한 최종 전체 정답률(87%), 개선 전 정답률(55%), 상승 폭(32%p)을 모두 정확히 포함하고 있다. 추가로 중간 수치(80%)를 언급했으나, 이는 맥락 설명일 뿐 핵심 요구 사실에 영향을 주지 않는다. tool query도 전체 의미를 보존하며 적절하다.

---

### C-SE02 · semantic_boundary · 부분일치

#### (정답)

**질문**
이번 유지보수에 들어간 총 인건비나 전체 프로젝트 비용은 얼마야?

**답변**

> 문서에서 확인할 수 없다. 월 API 비용 증가분 3~5만 원만 언급됐고 총인건비나 전체 프로젝트 비용은 기록되지 않았다.

**참고 문항(출처)**
sources/csbot/2026-06-02_유지보수요청_초기대응.md, sources/csbot/2026-06-09_진단결과_원인분석.md, sources/csbot/2026-06-16_개선방안_확정.md, sources/csbot/2026-06-23_QA결과검토_2차방향.md, sources/csbot/2026-06-27_최종QA_배포일정.md

**기대 도구** `search_project_evidence` · **최대 도구 라운드** `1`

**기대 호출/답변 계약**

```json
{
  "answer_contract": {
    "must_abstain": true,
    "required_terms": [
      "확인",
      "없",
      "3~5만"
    ],
    "type": "semantic_facts"
  },
  "tool_calls": [
    {
      "args_semantics": "질문 전체 의미를 보존",
      "name": "search_project_evidence"
    }
  ]
}
```

#### (실제)

**질문**
이번 유지보수에 들어간 총 인건비나 전체 프로젝트 비용은 얼마야?

**답변**

> 기록에 이번 유지보수에 들어간 총 인건비나 전체 프로젝트 비용에 관한 구체적인 금액 정보는 **확인되지 않는다**.

**참고 문항(반환 출처)**
2026-06-02_유지보수요청_초기대응.md, 2026-06-16_개선방안_확정.md, 2026-06-27_최종QA_배포일정.md, 2026-06-23_QA결과검토_2차방향.md, 2026-06-09_진단결과_원인분석.md

**실제 도구** `search_project_evidence` · **도구 라운드** `1`

**실제 호출**

```json
[
  {
    "args": {
      "query": "유지보수 인건비 총액, 전체 프로젝트 비용"
    },
    "name": "search_project_evidence"
  }
]
```

**API** `200` · **응답시간** `2759.4 ms` · **route** `semantic`

**결정론/계약 신호**

```json
{
  "answer_contract_score": {
    "category_count_checks": [],
    "matched": [
      "확인"
    ],
    "missing": [
      "없",
      "3~5만"
    ],
    "must_abstain": true,
    "strict_text_pass": false,
    "type": "semantic_facts"
  },
  "scores": {
    "answer_contract": {
      "kind": "lexical_proxy",
      "pass": false
    },
    "overall": {
      "pass": false
    },
    "response": {
      "pass": true
    },
    "tool_arguments": {
      "pass": true,
      "serialized_pass": true
    },
    "tool_rounds": {
      "pass": true
    },
    "tool_selection": {
      "pass": true
    }
  },
  "tool_score": {
    "actual_tools": [
      "search_project_evidence"
    ],
    "allowed_tools": [
      "search_project_evidence"
    ],
    "effective_args_pass": true,
    "exact_args_pass": true,
    "extra_tool_calls": 0,
    "max_tool_rounds": 1,
    "required_tools": [
      "search_project_evidence"
    ],
    "response_pass": true,
    "rounds_pass": true,
    "runner_original_exact_args_pass": true,
    "scoring_version": "effective-args-v1",
    "semantic_args_need_review": true,
    "serialized_args_pass": true,
    "tool_call_checks": [
      {
        "actual_candidates": [
          {
            "args": {
              "query": "유지보수 인건비 총액, 전체 프로젝트 비용"
            },
            "name": "search_project_evidence"
          }
        ],
        "args_semantics": "질문 전체 의미를 보존",
        "matched_required_args": true,
        "name": "search_project_evidence",
        "required_args": {}
      }
    ],
    "tool_rounds": 1,
    "tool_selection_pass": true
  }
}
```

#### 최종 답변 판정

**부분일치** · 신뢰도 `0.99` · semantic 검색 인자 `PASS`

총인건비와 전체 비용이 기록에 없다는 핵심 기권은 정확하다. 다만 계약이 요구하는 유일한 관련 금액인 월 API 비용 증가분 3~5만 원을 빠뜨렸다.

_동결 근거 재검토 적용: 자동 판정 PARTIAL → 최종 판정 PARTIAL_

```json
{
  "core_facts_missing": [
    "월 API 비용 증가분 3~5만 원"
  ],
  "failure_codes": [
    "MISSING_FACT"
  ]
}
```

---
