#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Stopping existing app.py processes in $DIR..."
ps aux | grep '[a]pp.py' | awk '{print $2}' | xargs kill -9 2>/dev/null

echo "Starting app.py..."
.venv/bin/python app.py
