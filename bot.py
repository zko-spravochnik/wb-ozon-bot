import os, asyncio, asyncpg, aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

PHONE, CARD, ADMIN_ID = "77058120376", "4400430344974149", 8993374736
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp, router, db_pool = Dispatcher(), Router(), None
dp.include_router(router)

class GeneratorStates(StatesGroup):
    choosing_platform = State(); entering_name = State(); entering_details = State()

async def get_user_balance(uid: int) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT generations_left FROM users WHERE user_id = $1", uid)
        if row is None:
            await conn.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, 3)", uid)
            return 3
        return row['generations_left']

def get_tinkoff_link(amount: int, uid: int) -> str:
    return f"https://tinkoff.ru{amount}&comment=ID{uid}"

@router.message(Command("start"))
async def start_cmd(message: Message):
    bal = await get_user_balance(message.from_user.id)
    await message.answer(f"Привет! 👋\nЯ — ИИ-генератор SEO-описаний карточек.\nТвой баланс: **{bal} генераций**.\n\nНажми кнопку ниже для старта!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✨ Создать описание")]], resize_keyboard=True), parse_mode="Markdown")
    @router.message(F.text == "✨ Создать описание")
async def start_generation(message: Message, state: FSMContext):
    if await get_user_balance(message.from_user.id) <= 0:
        uid = message.from_user.id
        ru_lnk = get_tinkoff_link(150, uid)
        return await message.answer(f"🛑 **Лимит исчерпан.**\n\nВыбери способ пополнения (50 генераций — 150 руб / 750 тг):\n\n🇷🇺 **РФ (Т-Банк):** Нажми кнопку ниже.\n\n🇰🇿 **КЗ (Kaspi):** Переведи 750 ₸ на карту:\n`{CARD}`\nВ комментарии укажи свой ID: `{uid}`", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплата из РФ", url=ru_lnk)]]), parse_mode="Markdown")
    await message.answer("Выберите маркетплейс:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Wildberries 🟣", callback_data="platform_wb")],[InlineKeyboardButton(text="Ozon 🔵", callback_data="platform_ozon")]]))
    await state.set_state(GeneratorStates.choosing_platform)

@router.callback_query(F.data.startswith("platform_"), GeneratorStates.choosing_platform)
async def platform_chosen(callback: Message, state: FSMContext):
    p = "Wildberries" if callback.data == "platform_wb" else "Ozon"
    await state.update_data(platform=p)
    await callback.message.edit_text(f"Выбран маркетплейс: **{p}**\n\nВведите название вашего товара:")
    await state.set_state(GeneratorStates.entering_name)

@router.message(GeneratorStates.entering_name)
async def name_entered(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text)
    await message.answer("Отправьте характеристики или ссылку на конкурента:")
    await state.set_state(GeneratorStates.entering_details)

@router.message(GeneratorStates.entering_details)
async def details_entered(message: Message, state: FSMContext):
    ud = await state.get_data(); await state.clear()
    w = await message.answer("🤖 *ИИ генерирует текст... Пожалуйста, подождите...*")
    pr = f"Напиши SEO описание для {ud['platform']}. Товар: {ud['product_name']}. Инфо: {message.text}. Выдай: 1) Текст (3 абзаца), 2) Ключевые слова (20 шт через запятую), 3) Советы (3 шт)."
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://pollinations.ai", json={"messages": [{"role": "user", "content": pr}], "model": "openai"}, timeout=30) as res:
                text = await res.text()
        async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET generations_left = generations_left - 1 WHERE user_id = $1", message.from_user.id)
        nb = await get_user_balance(message.from_user.id)
        await w.delete(); await message.answer(f"✅ **Готово!**\n\n{text}\n\n📉 Остаток: {nb}", parse_mode="Markdown")
    except: await w.delete(); await message.answer("❌ Ошибка ИИ, повторите позже.")

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
    
