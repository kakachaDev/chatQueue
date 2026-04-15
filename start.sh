#!/bin/bash
set -e
cd "$(dirname "$0")"

# Останавливаем watchdog, если запущен
if [ -f watchdog.pid ] && kill -0 "$(cat watchdog.pid)" 2>/dev/null; then
    echo "Stopping old watchdog (PID $(cat watchdog.pid))..."
    kill "$(cat watchdog.pid)"
    sleep 1
fi

# Останавливаем бот, если запущен
if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
    echo "Stopping old bot (PID $(cat bot.pid))..."
    kill "$(cat bot.pid)"
    sleep 1
fi

rm -f watchdog.pid bot.pid

# Запускаем watchdog-цикл: бот перезапускается автоматически при падении
(
    while true; do
        .venv/bin/python3 bot.py >> bot.log 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot exited, restarting in 10s..." >> bot.log
        sleep 10
    done
) &

echo $! > watchdog.pid
echo "Bot started (watchdog PID $(cat watchdog.pid))"
