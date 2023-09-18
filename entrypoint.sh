#!/bin/bash


export $(grep -v '^#' .env | xargs)

cd python

# Run cron.py in the background
# python cron.py &

# Run main.py
uvicorn main:app --host 0.0.0.0 --port 5000
