#!/bin/bash

cd python

export $(grep -v '^#' .env | xargs)

# Run cron.py in the background
python cron.py &

# Run main.py
uvicorn main:app --host 0.0.0.0 --port 8000
