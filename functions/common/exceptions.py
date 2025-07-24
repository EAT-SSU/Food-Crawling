class HolidayException(Exception):
    def __init__(self, target_date, raw_data):
        super().__init__(f"날짜 {target_date}는 휴무일입니다. raw_data: {raw_data}")
        self.target_date = target_date
        self.raw_data = raw_data


class MenuFetchException(Exception):
    def __init__(self, target_date, raw_data):
        super().__init__(f"날짜({target_date})의 메뉴 조회 실패: {raw_data}")
        self.target_date = target_date
        self.raw_data = raw_data


class MenuParseException(Exception):
    def __init__(self, target_date, error_details):
        super().__init__(f"날짜({target_date})의 메뉴 파싱 실패")
        self.target_date = target_date
        self.details = error_details


class WeirdRestaurantName(Exception):
    def __init__(self, target_date, restrant_name, restrant_meal_time):
        super().__init__(f"{target_date}의 {restrant_name}에 중식과 석식이 아닌 메뉴가 존재합니다. {restrant_meal_time}이라는 식사 시간이 추가된 듯 합니다.")
        self.target_date = target_date
        self.restrant_name = restrant_name
