from Object import Dodam_or_School_Cafeteria
from Object import Dormitory
from datetime import date





def getmenu(restaurantType:int, date:str):
    a=Dodam_or_School_Cafeteria(restaurantType,date)   
    a.get_menu()
    print(a)

# getmenu("1","20230501")

def getDorm(year,month,day):
    a=Dormitory(year,month,day)
    a.refine_table()
    a.get_table()

# d = date(2023, 5, 1)
# str_date = d.strftime('%Y%m%d')

# getDorm(2023,4,1)

getmenu(1,"20230421")