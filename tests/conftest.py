"""테스트 공통 설정.

기존 테스트들은 JWT 도입 이전의 단일 사용자 동작(핸들러 직접 호출,
require_project_access 패치)을 전제하므로 suite 전체를 dev 모드로 실행한다.
jwt 모드(fail-closed) 자체의 동작은 tests/test_auth_jwt.py가
PAIM_AUTH_MODE를 개별적으로 override해 검증한다.
"""
import os

os.environ.setdefault("PAIM_AUTH_MODE", "dev")

import pytest

from backend.rate_limit import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """endpoint 호출 순서와 무관하게 각 테스트에 빈 limiter state를 제공한다."""
    limiter.reset()
    yield
    limiter.reset()


def pytest_configure(config):
    """하네스 계약의 안정적 행위 ID marker.

    수용 기준이 함수 이름 대신 이 ID 집합을 계약으로 삼는다 —
    이름을 바꿔도 계약이 유지된다(tests/test_harness_contract.py).
    """
    config.addinivalue_line(
        "markers", "behavior(*ids): 하네스 계약의 안정적 행위 ID"
    )
