# preflight 음성 fixture

`run.sh --check` 가 **실제로 실패하는지** 파일만 읽고 판정할 수 있게 고정한 것이다.

구현자의 mutation 기록은 독립 증거가 아니므로(AC-10), 검증자가 읽기 전용으로
직접 실행해 확인할 수 있어야 한다. 여기 있는 compose 는 **쓰기 없이** 검사되며
read-only 세션에서도 돈다.

```bash
HARNESS_COMPOSE_FILE=tests/integration/mysql/fixtures/<파일> \
  ./tests/integration/mysql/run.sh --check
```

| 파일 | 무엇을 깨뜨렸나 | 기대 사유 |
|---|---|---|
| `compose-missing-migration.yml` | 없는 마이그레이션 경로 | `없는 경로` |
| `compose-escapes-repo.yml` | bind mount 가 `/etc/hostname` | `저장소 밖을 가리킨다` |

**Git 상태가 필요한 케이스는 여기 둘 수 없다.** "추적되지 않는 파일" 이나
"미추적 심볼릭 링크가 추적된 파일을 가리킴" 은 index 를 조작해야 재현되므로
`tests/test_harness_contract.py` 의 `sandbox` fixture(임시 Git 저장소)가 담당한다.

| 케이스 | 방식 | read-only 판정 |
|---|---|---|
| 없는 경로 | 이 디렉터리 | **가능** |
| 저장소 밖 | 이 디렉터리 | **가능** |
| 미추적 참조 | sandbox | 불가 (쓰기 필요) |
| 미추적 링크 → 추적 파일 | sandbox | 불가 (쓰기 필요) |

**운영 경로에서 쓰지 않는다.** `HARNESS_COMPOSE_FILE` 은 `--check` 에서만 허용된다.
