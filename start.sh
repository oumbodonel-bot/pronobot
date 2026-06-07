#!/bin/bash
apt-get update
apt-get install -y libpq5
python3 -m pip install --upgrade pip
pip install psycopg2-binary==2.9.9
pip install httpx==0.27.0
pip install python-telegram-bot==21.3
pip install python-dotenv==1.0.1
python bot.py
