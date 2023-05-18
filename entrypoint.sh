#!/bin/bash

cd python
# Run cron.py in the background
python cron.py &

# Run main.py
uvicorn python.main:app --host 0.0.0.0 --port 8000
