# base image
FROM python:3.9-slim-buster

# install pip
RUN apt-get update && apt-get install -y python3-pip

# set working directory
WORKDIR /app

# install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy application files
COPY . .

# expose port
EXPOSE 8000

# run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]