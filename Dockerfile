FROM python:3.9-slim-buster

# install pip
RUN apt-get update && apt-get install -y python3-pip cron

# set working directory
WORKDIR /app

# copy the requirements file
COPY . .

# install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 파이썬 경로 잡아주기
ENV PYTHONPATH=/app/python

# expose port
EXPOSE 8000

# make the entrypoint script executable
RUN chmod +x entrypoint.sh

# run the entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
