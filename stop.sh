#!/bin/bash
cd "$(dirname "$0")"

STOPPED=0

# Останавливаем watchdog (чтобы не перезапускал бота)
if [ -f watchdog.pid ] && kill -0 "$(cat watchdog.pid)" 2>/dev/null; then
    echo "Stopping watchdog (PID $(cat watchdog.pid))..."
    kill "$(cat watchdog.pid)"
    rm -f watchdog.pid
    STOPPED=1
fi

# Останавливаем бот
if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
    echo "Stopping bot (PID $(cat bot.pid))..."
    kill "$(cat bot.pid)"
    rm -f bot.pid
    STOPPED=1
fi

if [ "$STOPPED" -eq 1 ]; then
    echo "Done."
else
    echo "Bot is not running."
    rm -f watchdog.pid bot.pid
fi
