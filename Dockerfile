FROM python:3.9-slim-buster

# install pip
RUN apt-get update && apt-get install -y python3-pip

# set working directory
WORKDIR /app

# copy the requirements file
COPY food-crawling/python/requirements.txt .

# install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# copy the application files
COPY food-crawling /app/food-crawling

# expose port
EXPOSE 8000

# run the application
CMD ["uvicorn", "python.main:app", "--host", "0.0.0.0", "--port", "8000"]