import pytest
import requests


# request 보내는 테스트

@pytest.mark.integration
def test_lambda_handler():
    response = requests.get("https://drvrj3q50b.execute-api.ap-northeast-2.amazonaws.com/scheduleDodam",
                             params={"delayed_schedule": False})

    return response
    # assert response.status_code == 200



if __name__ == '__main__':
    res = test_lambda_handler()