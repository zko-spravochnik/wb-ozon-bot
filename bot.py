import os, asyncio, asyncpg, aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

PHONE, CARD, ADMIN_ID = "77058120376", "4400430344974149", 8993374736
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp, router, pool = Dispatcher(), Router(), None
dp.include_router(router)

async def http_handler(reader, writer):
    try:
        await reader.read(1024)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 4\r\nConnection: close\r\n\r\nLive")
        await writer.drain()
    finally:
        writer.close()
        try: await writer.wait_closed()
        except: pass

async def get_balance(uid: int) -> int:
    conn = pool
    row = await conn.fetchrow("SELECT generations_left FROM users WHERE user_id = $1", uid)
    if not row:
        await conn.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, 3)", uid)
        return 3
    return row['generations_left']

@router.message(Command("start"))
async def start(message: Message):
    bal = await get_balance(message.from_user.id)
    await message.answer(f"Привет! Пришли одним сообщением название товара и его характеристики.\n\nБесплатных генераций осталось: {bal}.")

@router.message(Command("give"))
async def give(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        uid, amount = int(parts[1]), int(parts[2])
        await pool.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET generations_left = users.generations_left + EXCLUDED.generations_left", uid, amount)
        await message.answer(f"Добавлено генераций пользователю {uid}: {amount}")
    except:
        await message.answer("Формат: /give ID КОЛИЧЕСТВО")

@router.message(F.text)
async def handle_product(message: Message):
    if message.text.startswith("/"): return
    uid = message.from_user.id
    bal = await get_balance(uid)
    if bal <= 0:
        ru_lnk = f"https://tinkoff.ru{PHONE}&card=2200700942512566&amount=150&comment=ID{uid}"
        return await message.answer(f"🛑 Бесплатные генерации закончились.\n\n🇷🇺 РФ - Т-Банк: Перевод по телефону {PHONE} или карте 2200700942512566\n🇰🇿 Казахстан - Kaspi Gold:\n`{CARD}`\n\nПосле оплаты обратитесь к администратору.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплата из РФ", url=ru_lnk)]]))
    
    status = await message.answer("🤖 *Создаю SEO-описание...*")
    prompt = f"Создай SEO-карточку товара для Wildberries и Ozon. Название и характеристики товара: {message.text}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post("https://text.pollinations.ai/openai", json={"model": "openai", "messages": [{"role": "user", "content": prompt}]}) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
                res_text = data["choices"][0]["message"]["content"] if isinstance(data, dict) else str(data)
        
        await pool.execute("UPDATE users SET generations_left = generations_left - 1 WHERE user_id = $1", uid)
        nb = await get_balance(uid)
        await status.delete()
        await message.answer(f"✅ **Готово!**\n\n{res_text}\n\n📉 Остаток: {nb}", parse_mode="Markdown")
    except Exception as e:
        await pool.execute("UPDATE users SET generations_left = generations_left + 1 WHERE user_id = $1", uid)
        await status.edit_text("Не удалось получить ответ от ИИ. Попробуйте позже.")

async def main():
    global pool
    token = os.environ["BOT_TOKEN"]
    db_url = os.environ["DATABASE_URL"]
    if "sslmode" not in db_url:
        db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    
    server = await asyncio.start_server(http_handler, "0.0.0.0", int(os.getenv("PORT", "10000")))
    pool = await asyncpg.connect(db_url)
    
    async with Bot(token=token) as bot, server:
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
