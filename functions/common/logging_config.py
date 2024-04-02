from logging.config import dictConfig
import logging


class ContextFilter(logging.Filter):
    def __init__(self, function_name):
        super().__init__()
        self.function_name = function_name

    def filter(self, record):
        record.function_name = self.function_name
        return True


def setup_logging(function_name="default"):
    logging_config = {
        'version': 1,
        'filters': {
            'context_filter': {
                '()': 'functions.common.logging_config.ContextFilter',  # ContextFilter 클래스의 실제 모듈 경로를 사용하세요.
                'function_name': function_name,  # 동적으로 function_name을 설정합니다.
            }
        },
        'formatters': {
            'standard': {
                'format': '%(asctime)s : %(levelname)s : %(function_name)s : %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'standard',
                'filters': ['context_filter'],
            },
        },
        'loggers': {
            '': {  # root logger
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
        },
    }

    dictConfig(logging_config)


# 사용 예:
if __name__ == '__main__':
    # function_name = 'scheduled_haksik'  # 예를 들어, 실행 컨텍스트에 따라 결정되는 값
    setup_logging()

    # 이제 로거를 사용하여 로그 메시지를 기록할 수 있습니다.
    logger = logging.getLogger(__name__)
    logger.info("이것은 테스트 로그 메시지입니다.")
