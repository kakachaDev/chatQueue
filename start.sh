#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
    echo "Stopping old instance (PID $(cat bot.pid))..."
    kill "$(cat bot.pid)"
    sleep 1
fi

rm -f bot.pid

# Запускаем watchdog-цикл: бот перезапускается автоматически при падении
(
    while true; do
        .venv/bin/python3 bot.py >> bot.log 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot exited, restarting in 10s..." >> bot.log
        sleep 10
    done
) &

echo $! > bot.pid
echo "Bot started (PID $(cat bot.pid))"
