from quart import Quart, request, jsonify
import yfinance as yf
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import asyncio

app = Quart(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

def init_db():
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            target_price REAL,
            active INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def add_target(user_id, symbol, target_price):
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO targets (user_id, symbol, target_price)
        VALUES (?, ?, ?)
    ''', (user_id, symbol, target_price))
    conn.commit()
    conn.close()

def deactivate_target(user_id, symbol):
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE targets
        SET active = 0
        WHERE user_id = ? AND symbol = ? AND active = 1
    ''', (user_id, symbol))
    conn.commit()
    conn.close()

def get_active_targets(user_id):
    conn = sqlite3.connect('db.sqlite3')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT symbol, target_price
        FROM targets
        WHERE user_id = ? AND active = 1
    ''', (user_id,))
    targets = cursor.fetchall()
    conn.close()
    return targets

def get_stock_price(symbol):
    stock = yf.Ticker(symbol)
    stock_history = stock.history(period="1d")
    return stock_history['Close'].iloc[-1]

async def check_targets():
    while True:
        try:
            conn = sqlite3.connect('db.sqlite3')
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT user_id FROM targets WHERE active = 1')
            users = cursor.fetchall()
            for (user_id,) in users:
                targets = get_active_targets(user_id)
                for symbol, target_price in targets:
                    current_price = get_stock_price(symbol)
                    print(current_price)
                    await telegram_app.bot.send_message(chat_id=user_id, text=f"{symbol} is now at {current_price}")
                    if current_price >= target_price:
                        await telegram_app.bot.send_message(chat_id=user_id, text=f"Target reached! {symbol} is now at {current_price}")
                        deactivate_target(user_id, symbol)
            conn.close()
        except Exception as e:
            telegram_app.bot.send_message(chat_id=user_id, text=f"Error in check_targets: {e}")
        await asyncio.sleep(10)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /settarget SYMBOL PRICE to set a target.")

async def set_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /settarget SYMBOL PRICE")
        return
    symbol = args[0].upper()
    try:
        target_price = float(args[1])
    except ValueError:
        await update.message.reply_text("Invalid price format.")
        return
    if target_price <= 0:
        await update.message.reply_text("Price must be greater than zero.")
        return
    add_target(update.message.from_user.id, symbol, target_price)
    await update.message.reply_text(f"Target set for {symbol} at {target_price}.")

async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /deactivatetarget SYMBOL")
        return
    symbol = args[0].upper()
    deactivate_target(update.message.from_user.id, symbol)
    await update.message.reply_text(f"Target deactivated for {symbol}.")

async def list_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    targets = get_active_targets(update.message.from_user.id)
    if targets:
        message = "```\n"
        message += "Symbol     | Target Price | Current Price\n"
        message += "-----------|--------------|--------------\n"
        
        for symbol, target_price in targets:
            current_price = get_stock_price(symbol)
            message += f"{symbol.ljust(10)} | {str(target_price).ljust(12)} | {str(current_price).ljust(12)}\n"
        
        message += "```"
    else:
        message = "You have no active targets."
    
    await update.message.reply_text(message, parse_mode="MarkdownV2")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("settarget", set_target))
telegram_app.add_handler(CommandHandler("deactivatetarget", deactivate))
telegram_app.add_handler(CommandHandler("listtargets", list_targets))

@app.route('/webhook', methods=['POST'])
async def webhook():
    data = await request.get_json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return jsonify(success=True)

@app.route('/')
async def health():
    return jsonify({"status": "ok"})

@app.before_serving
async def startup():
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(check_targets())
    await telegram_app.start()

@app.after_serving
async def shutdown():
    await telegram_app.stop()
    await telegram_app.shutdown()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
