# food-crawling
숭실대 내의 식당 1. 학생식당, 2. 도담식당, 3.기숙사식당 의 정보를 스크래핑하는 Fastapi 기반 서버입니다.
## 배포 방법 처음 배포할 경우
```bash
git clone https://github.com/EAT-SSU/food-crawling.git
cd food-crawling
docker build -t fastapi_crawling .
docker run -i -t --env-file ./.env -p 5000:5000 --restart=always fastapi_crawling
```

## 인스턴스에 다시 배포할 경우
```bash
cd food-crawling
git pull
docker build -t fastapi_crawling .
docker run -i -t --env-file ./.env -p 5000:5000 --restart=always fastapi_crawling
```
