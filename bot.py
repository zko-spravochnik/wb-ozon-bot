import os
import asyncio
import json
import aiohttp
import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# Render Environment Variables:
# BOT_TOKEN = Telegram bot token
# DATABASE_URL = Supabase PostgreSQL connection string (get from Supabase > Connect)
# Never put Supabase secret/service-role keys in source code.
ADMIN_ID = 8993374736
KASPI_CARD = "4400430344974149"
TBANK_PHONE = "77058120376"
TBANK_CARD = "2200700942512566"

dp = Dispatcher()
pool = None
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=45)

async def get_balance(uid: int) -> int:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(user_id, generations_left) VALUES($1, 3) "
            "ON CONFLICT(user_id) DO NOTHING", uid
        )
        return await conn.fetchval(
            "SELECT generations_left FROM users WHERE user_id=$1", uid
        )

async def generate_text(product: str) -> str:
    prompt = (
        "Создай SEO-карточку товара для Wildberries и Ozon на русском языке. "
        "Не выдумывай свойства, которых нет во входных данных. "
        "Строго выведи: 1) SEO-описание ровно из 3 абзацев; "
        "2) 20 ключевых слов через запятую; 3) 3 практических совета. "
        "Название и характеристики товара: " + product
    )
    url = "https://text.pollinations.ai/openai"
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
        async with session.post(
            url, json={"model": "openai", "messages": [
                {"role": "user", "content": prompt}
            ]}
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
            if isinstance(data, dict):
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return str(data.get("content", data))
            return str(data)

async def http_handler(reader, writer):
    try:
        await reader.read(1024)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
            b"Content-Length: 2\r\nConnection: close\r\n\r\nOK"
        )
        await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

@dp.message(Command("start"))
async def start(message: Message):
    bal = await get_balance(message.from_user.id)
    await message.answer(
        "Привет! Пришли одним сообщением название товара и его характеристики. "
        f"Бесплатных генераций осталось: {bal}."
    )

@dp.message(Command("give"))
async def give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Команда доступна только администратору.")
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return await message.answer("Формат: /give ID КОЛИЧЕСТВО")
    uid, amount = int(parts[1]), int(parts[2])
    if amount < 1:
        return await message.answer("Количество должно быть больше нуля.")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(user_id,generations_left) VALUES($1,$2) "
            "ON CONFLICT(user_id) DO UPDATE SET generations_left="
            "users.generations_left + EXCLUDED.generations_left", uid, amount
        )
    await message.answer(f"Добавлено генераций пользователю {uid}: {amount}.")

@dp.message()
async def handle_product(message: Message):
    product = (message.text or "").strip()
    if not product or product.startswith("/"):
        return
    uid = message.from_user.id
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO users(user_id,generations_left) VALUES($1,3) "
                "ON CONFLICT(user_id) DO NOTHING", uid
            )
            updated = await conn.fetchval(
                "UPDATE users SET generations_left=generations_left-1 "
                "WHERE user_id=$1 AND generations_left>0 RETURNING generations_left",
                uid
            )
    if updated is None:
        await message.answer(
            "Бесплатные генерации закончились.\n\n"
            "🇷🇺 РФ — Т-Банк: откройте перевод по телефону "
            f"{TBANK_PHONE} (карта {TBANK_CARD}).\n"
            "🇰🇿 Казахстан — Kaspi Gold: "
            f"{KASPI_CARD}\n"
            "После оплаты обратитесь к администратору для пополнения."
        )
        return
    status = await message.answer("🤖 Создаю SEO-описание…")
    try:
        result = await generate_text(product)
        if not result.strip():
            raise ValueError("Empty AI response")
        await status.delete()
        await message.answer(result[:4000])
        await message.answer(f"Осталось генераций: {updated}.")
    except Exception:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET generations_left=generations_left+1 WHERE user_id=$1",
                uid
            )
        await status.edit_text("Не удалось получить ответ ИИ. Попытка возвращена, попробуйте позже.")

async def main():
    global pool
    token = os.environ["BOT_TOKEN"]
    db_url = os.environ["DATABASE_URL"]
    if "sslmode=" not in db_url:
        db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
    # Start listening before database connection so Render can detect the port.
    server = await asyncio.start_server(
        http_handler, "0.0.0.0", int(os.getenv("PORT", "10000"))
    )
    try:
        pool = await asyncpg.create_pool(
            db_url, statement_cache_size=0, min_size=1, max_size=3
        )
        async with Bot(token=token) as bot, server:
            await asyncio.gather(server.serve_forever(), dp.start_polling(bot))
    finally:
        server.close()
        await server.wait_closed()
        if pool:
            await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
