from datetime import date, timedelta,datetime
import os
from Object import Dodam_or_School_Cafeteria
from Object import Dormitory



# d = date(2023, 5, 1)
# str_date = d.strftime('%Y%m%d')


new_path = "C:/Users/rover0811/Desktop/Github/food-crawling/python"
os.chdir(new_path)

# start_date = date(2020, 1, 2)  # 시작일자
# end_date = date(2023, 5, 1)  # 종료일자
# step = timedelta(weeks=1)  # 1주일씩 증가


# def scrapping_school_cafeteria(start,end):
#     step = timedelta(days=1)  # 1주일씩 증가

#     with open('../data/school_cafeteria.csv', 'w') as f:  # 파일을 열고 쓰기 모드로 엽니다
#         while start <= end:
#             if (start.weekday()==5 or start.weekday()==6):
#                 start += step
#                 continue

#             try:
#                 today_date=start.strftime('%Y%m%d')
#                 print(today_date)
#                 today_menu=Dodam_or_School_Cafeteria(1,today_date).get_menu()
#                 print(today_menu)
#                 for k,v in today_menu.items():
#                     f.write(f'"{today_date}","{k}","{v}"')  # 결과를 파일에 씁니다
#                 start += step  # 날짜 증가
#             except AttributeError:
#                 start += step
#                 continue
            
def scrapping_school_cafeteria(start, end): # 개느리다...
    step = timedelta(days=1)  # 1주일씩 증가
    results = []
    with open(f'../data/school_cafeteria_{start.strftime("%Y%m%d")}~{end.strftime("%Y%m%d")}.csv', 'w') as f:
        while start <= end:
            if (start.weekday() == 5 or start.weekday() == 6):
                start += step
                continue

            try:
                today_date = start.strftime('%Y%m%d')
                today_menu = Dodam_or_School_Cafeteria(1, today_date).get_menu()
                print(today_date)

                for k, v in today_menu.items():
                    results.append((today_date, k, v))
                start += step
            except AttributeError:
                start += step
                continue


            start += step  # 날짜 증가

            for result in results:
                f.write(f'"{result[0]}","{result[1]}","{result[2]}"\n')

def scrapping_dodam(start,end):
    step = timedelta(days=1)  # 1주일씩 증가
    results = []
    with open(f'../data/dodam_{start.strftime("%Y%m%d")}~{end.strftime("%Y%m%d")}.csv', 'w') as f:

        while start <= end:
            if (start.weekday() == 5 or start.weekday() == 6):
                start += step
                continue

            try:
                today_date = start.strftime('%Y%m%d')
                today_menu = Dodam_or_School_Cafeteria(2, today_date).get_menu()
                print(today_date)

                for k, v in today_menu.items():
                    results.append((today_date, k, v))
                start += step
            except AttributeError:
                start += step
                continue
            start += step  # 날짜 증가

        for result in results:
            f.write(f'"{result[0]}","{result[1]}","{result[2]}"\n')

def scrapping_dormitory(start,end):
    step = timedelta(weeks=1)  # 1주일씩 증가
    with open(f'../data/dormitory_{start.strftime("%Y%m%d")}~{end.strftime("%Y%m%d")}.csv', 'w') as f:
        while start <= end:
            year=start.year
            month = start.month
            day = start.day

            today_menu=Dormitory(year,month,day).refine_table()
            today_menu.to_csv(f)
            start += step  # 날짜 증가


if __name__ == "__main__":
    print("hi")
    # scrapping_school_cafeteria(date(2022,11,7),date(2023,5,1))
    # scrapping_dodam(date(2022,11,7),date(2023,5,1))
    scrapping_dormitory(date(2020,3,16),date(2023,5,1))

   