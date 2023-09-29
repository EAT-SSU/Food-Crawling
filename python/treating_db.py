import pymysql
import os
from dotenv import load_dotenv

load_dotenv()


# 데이터베이스 연결 정보
host = os.environ.get("DB_ENDPOINT")  # MySQL 호스트 주소
user = 'admin'     # MySQL 사용자명
password = os.environ.get("DB_PASSWORD") # MySQL 비밀번호
database = 'eat-ssu'  # 사용할 데이터베이스명
# eat-ssu
# eatssu
# information_schema
# mysql
# performance_schema
# sys


# try:
#     # MySQL에 연결
#     connection = pymysql.connect(
#         host=host,
#         user=user,
#         password=password
#     )

#     # 커서 생성
#     cursor = connection.cursor()

#     # 데이터베이스 목록 확인 쿼리
#     show_databases_query = "SHOW DATABASES"

#     # 쿼리 실행
#     cursor.execute(show_databases_query)

#     # 결과 가져오기
#     databases = cursor.fetchall()

#     # 데이터베이스 목록 출력
#     print("사용 가능한 데이터베이스 목록:")
#     for database in databases:
#         print(database[0])

# except pymysql.MySQLError as e:
#     print("MySQL 에러:", e)
# finally:
#     # 연결 종료
#     if connection:
#         connection.close()


try:
    # MySQL에 연결
    connection = pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database
    )

    # 커서 생성
    cursor = connection.cursor()

    # 테이블 목록 확인 쿼리
    show_tables_query = "SHOW TABLES"

    # 쿼리 실행
    cursor.execute(show_tables_query)

    # 결과 가져오기
    tables = cursor.fetchall()

    # 테이블 목록 출력
    print("테이블 목록:")
    for table in tables:
        print(table[0])

except pymysql.MySQLError as e:
    print("MySQL 에러:", e)
# finally:
#     # 연결 종료
#     if connection:
#         connection.close()
