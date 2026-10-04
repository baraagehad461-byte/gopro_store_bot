from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "✅ GoPro Store Telegram Bot is alive and running!"

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
