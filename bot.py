import os, asyncio, asyncpg, requests
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

PHONE, CARD, ADMIN_ID = "77058120376", "2200700942512566", 8993374736
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
    return f"https://tinkoff.ru{PHONE}&card={CARD}&amount={amount}&comment=ID{uid}"

@router.message(Command("start"))
async def start_cmd(message: Message):
    bal = await get_user_balance(message.from_user.id)
    await message.answer(f"Привет, продавец! 👋\nЯ — ИИ-генератор SEO-описаний для WB и Ozon.\nТвой баланс: **{bal} генераций**.\n\nНажми кнопку ниже для старта!", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✨ Создать описание")]], resize_keyboard=True), parse_mode="Markdown")

@router.message(F.text == "✨ Создать описание")
async def start_generation(message: Message, state: FSMContext):
    if await get_user_balance(message.from_user.id) <= 0:
        return await message.answer("🛑 **Лимит бесплатных генераций исчерпан.**\n\nВыберите пакет для пополнения через Т-Банк:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 10 шт — 100 руб", url=get_tinkoff_link(100, message.from_user.id))],
            [InlineKeyboardButton(text="🔥 50 шт — 300 руб", url=get_tinkoff_link(300, message.from_user.id))]
        ]), parse_mode="Markdown")
    await message.answer("Выберите целевой маркетплейс:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Wildberries 🟣", callback_data="platform_wb")], [InlineKeyboardButton(text="Ozon 🔵", callback_data="platform_ozon")]
    ]))
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
    await message.answer("Отлично! Теперь отправьте краткие характеристики товара или ссылку на конкурента:")
    await state.set_state(GeneratorStates.entering_details)

@router.message(GeneratorStates.entering_details)
async def details_entered(message: Message, state: FSMContext):
    ud = await state.get_data(); await state.clear()
    w = await message.answer("🤖 *ИИ генерирует текст... Подождите 5 секунд...*", parse_mode="Markdown")
    pr = f"Напиши SEO описание товара для {ud['platform']}.\nТовар: {ud['product_name']}\nИнфо: {message.text}\nВыдай строго раздельно: 1) Продающий текст (3 абзаца), 2) Блок '🔥 КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА:' (20 шт через запятую), 3) Блок '💡 РЕКОМЕНДАЦИИ ПО ХАРАКТЕРИСТИКАМ:' (3 совета)."
    try:
        res = requests.post("https://pollinations.ai", json={"messages": [{"role": "user", "content": pr}], "model": "openai"}, timeout=30)
        async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET generations_left = generations_left - 1 WHERE user_id = $1", message.from_user.id)
        nb = await get_user_balance(message.from_user.id)
        await w.delete(); await message.answer(f"✅ **Ваша SEO-карточка готова!**\n\n{res.text}\n\n📉 _Остаток: {nb}_", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✨ Создать описание")]], resize_keyboard=True), parse_mode="Markdown")
    except:
        await w.delete(); await message.answer("❌ Нейросеть временно занята. Повторите попытку.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✨ Создать описание")]], resize_keyboard=True))

@router.message(Command("give"))
async def give_balance(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = command.args.split(); tu, cnt = int(args[0]), int(args[1])
        async with db_pool.acquire() as conn: await conn.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET generations_left = users.generations_left + $2", tu, cnt)
        await message.answer(f"✅ Пользователю `{tu}` начислено +{cnt}!"); await bot.send_message(tu, f"🎉 Баланс пополнен! Вам начислено **+{cnt} генераций**.")
    except: await message.answer("⚠️ Формат: `/give ID КОЛИЧЕСТВО`")

async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"), statement_cache_size=0, min_size=1, max_size=3)
    server = await asyncio.start_server(lambda r, w: w.write(b"HTTP/1.1 200 OK\n\nLive"), "0.0.0.0", int(os.getenv("PORT", 10000)))
    await asyncio.gather(dp.start_polling(bot), server.serve_forever())

if __name__ == "__main__": asyncio.run(main())
    
