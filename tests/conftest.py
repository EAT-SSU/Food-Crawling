import subprocess
import time

import pytest
import requests


# conftest.py

def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") == "integration":
        # 통합 테스트 실행 시
        for item in items:
            if "integration" not in item.keywords:
                item.add_marker(pytest.mark.skip(reason="integration test only"))
    elif config.getoption("-m") == "unit":
        # 유닛 테스트 실행 시
        for item in items:
            if "unit" not in item.keywords:
                item.add_marker(pytest.mark.skip(reason="unit test only"))

@pytest.fixture(scope="session")
def sam_local_api():
    # SAM Local 프로세스 시작
    process = subprocess.Popen(
        ["sam", "local", "start-api"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Health check
    for _ in range(10):
        try:
            response = requests.get("http://127.0.0.1:3000/health")
            if response.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    else:
        pytest.fail("SAM Local API did not start in time")

    yield

    # Teardown: SAM Local 프로세스 종료
    process.terminate()
