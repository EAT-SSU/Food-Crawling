from crontab import CronTab
import sys

sys.path.append("/app/python/")

# crontab 객체 생성
cron = CronTab(user='root')  # 사용자명을 설정하여 crontab을 사용합니다.

# cron 작업 추가
job = cron.new(command='python3 ./api-notification.py')  # 실행할 명령어를 지정합니다.
job.setall('0 20 * * 0')  # 월요일부터 토요일까지 01:00에 실행하도록 스케줄을 설정합니다.


# cron 작업 저장
cron.write()