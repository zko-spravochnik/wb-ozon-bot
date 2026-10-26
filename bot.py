import os, asyncio, asyncpg, aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

PHONE, CARD, ADMIN_ID = "77058120376", "4400430344974149", 8993374736
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp, router, db_pool = Dispatcher(), Router(), None
dp.include_router(router)

async def get_user_balance(uid: int) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT generations_left FROM users WHERE user_id = $1", uid)
        if row is None:
            await conn.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, 3)", uid)
            return 3
        return row['generations_left']

@router.message(Command("start"))
async def start_cmd(message: Message):
    bal = await get_user_balance(message.from_user.id)
    await message.answer(
        f"Привет, продавец! 👋\n\nЯ — автономный ИИ-генератор идеальных SEO-описаний карточек для Wildberries и Ozon.\n"
        f"Твой баланс: **{bal} генераций**.\n\n"
        f"✍️ **Просто пришли мне название товара и его краткие характеристики (или ссылку на конкурента) в одном сообщении**, и я сразу сделаю мощную карточку!",
        parse_mode="Markdown"
    )

@router.message(F.text)
async def generate_seo(message: Message):
    if message.text.startswith("/"): return
    
    uid = message.from_user.id
    bal = await get_user_balance(uid)
    
    if bal <= 0:
        ru_lnk = f"https://tinkoff.ru{PHONE}&card=2200700942512566&amount=150&comment=ID{uid}"
        return await message.answer(
            f"🛑 **Лимит бесплатных генераций исчерпан.**\n\n"
            f"Выберите удобный способ пополнения (50 генераций — 150 руб / 750 тенге):\n\n"
            f"🇷🇺 **Для России (Т-Банк):** Нажмите кнопку ниже, оплатите форму, баланс обновится автоматически.\n\n"
            f"🇰🇿 **Для Казахстана (Kaspi.kz):** Переведите **750 ₸** на карту Kaspi Gold:\n`{CARD}`\n\nВ комментарии к переводу ОБЯЗАТЕЛЬНО укажите ваш `ID: {uid}`. После перевода админ моментально начислит баланс!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплата из РФ (Т-Банк)", url=ru_lnk)]]),
            parse_mode="Markdown"
        )
        
    w = await message.answer("🤖 *ИИ собирает поисковые ключи и генерирует карточку товара... Пожалуйста, подождите 5 секунд...*", parse_mode="Markdown")
    pr = f"Ты топовый копирайтер маркетплейсов. Напиши мощное продающее SEO описание товара на основе этих данных: {message.text}. Выдай строго раздельно: 1) Продающий текст (3 абзаца), 2) Блок '🔥 КЛЮЧЕВЫЕ СЛОВА:' (20 шт через запятую), 3) Блок '💡 СОВЕТЫ ПО ЗАПОЛНЕНИЮ:' (3 параметра)."
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://pollinations.ai", json={"messages": [{"role": "user", "content": pr}], "model": "openai"}, timeout=30) as res:
                text = await res.text()
        async with db_pool.acquire() as conn: 
            await conn.execute("UPDATE users SET generations_left = generations_left - 1 WHERE user_id = $1", uid)
        nb = await get_user_balance(uid)
        await w.delete()
        await message.answer(f"✅ **Ваша SEO-карточка успешно сгенерирована!**\n\n{text}\n\n📉 _Остаток генераций: {nb}_", parse_mode="Markdown")
    except:
        await w.delete()
        await message.answer("❌ Нейросеть временно занята. Повторите попытку чуть позже.")

async def start_fake_server():
    port = int(os.getenv("PORT", 10000))
    async def handler(r, w):
        w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nLive")
        await w.drain(); w.close(); await w.wait_closed()
    server = await asyncio.start_server(handler, "0.0.0.0", port)
    async with server: await server.serve_forever()

async def main():
    global db_pool
    db_url = os.getenv("DATABASE_URL")
    if "sslmode" not in db_url: db_url += "&sslmode=require" if "?" in db_url else "?sslmode=require"
    db_pool = await asyncpg.create_pool(db_url, statement_cache_size=0, min_size=1, max_size=3)
    await asyncio.gather(dp.start_polling(bot), start_fake_server())

if __name__ == "__main__": asyncio.run(main())
    
