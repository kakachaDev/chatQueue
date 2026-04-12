#!/bin/bash
set -e

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Создан .env — заполни переменные перед запуском."
fi

echo "Готово. Запуск: ./start.sh"
