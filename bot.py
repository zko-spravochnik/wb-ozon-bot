import os
import asyncio
import asyncpg
import requests
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==================== ОБЯЗАТЕЛЬНЫЕ НАСТРОЙКИ АДМИНИСТРАТОРА ====================
TINKOFF_PHONE = "77058120376"  
TINKOFF_CARD = "2200700942512566"   
ADMIN_ID = 8993374736           

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

db_pool = None

async def init_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, min_size=1, max_size=3)

async def get_user_balance(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT generations_left FROM users WHERE user_id = $1", user_id)
        if row is None:
            await conn.execute("INSERT INTO users (user_id, generations_left) VALUES ($1, 3)", user_id)
            return 3
        return row['generations_left']

async def decrease_balance(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET generations_left = generations_left - 1 WHERE user_id = $1", user_id)

async def add_balance_admin(user_id: int, count: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, generations_left) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET generations_left = users.generations_left + $2", 
            user_id, count
        )

class GeneratorStates(StatesGroup):
    choosing_platform = State()
    entering_name = State()
    entering_details = State()

def get_tinkoff_link(amount: int, user_id: int) -> str:
    comment = f"ID{user_id}"
    return f"https://tinkoff.ru{TINKOFF_PHONE}&card={TINKOFF_CARD}&amount={amount}&comment={comment}"

def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="✨ Создать описание")]], resize_keyboard=True)

def platform_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Wildberries 🟣", callback_data="platform_wb")],
        [InlineKeyboardButton(text="Ozon 🔵", callback_data="platform_ozon")]
    ])

def tariff_keyboard(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Пачка 10 шт — 100 руб", url=get_tinkoff_link(100, user_id))],
        [InlineKeyboardButton(text="🔥 Пачка 50 шт — 300 руб", url=get_tinkoff_link(300, user_id))],
        [InlineKeyboardButton(text="🚀 Пачка 200 шт — 800 руб", url=get_tinkoff_link(800, user_id))],
    ])
@router.message(Command("start"))
async def start_cmd(message: Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(
        f"Привет, продавец! 👋\n\nЯ — автономный ИИ-генератор идеальных SEO-описаний для Wildberries и Ozon.\n"
        f"Твой баланс: **{balance} генераций**.\n\nНажми кнопку ниже, чтобы начать работу!",
        reply_markup=main_keyboard(), parse_mode="Markdown"
    )

@router.message(F.text == "✨ Создать описание")
async def start_generation(message: Message, state: FSMContext):
    balance = await get_user_balance(message.from_user.id)
    if balance <= 0:
        await message.answer(
            "🛑 **Лимит бесплатных генераций исчерпан.**\n\n"
            "Чтобы продолжить выводить карточки в ТОП, выберите подходящий пакет.\n"
            "Нажмите на нужный тариф — откроется платежная форма. Оплатите её, "
            "и ваш баланс обновится после проверки администратором (в назначении платежа автоматически укажется ваш ID).",
            reply_markup=tariff_keyboard(message.from_user.id), parse_mode="Markdown"
        )
        return
    await message.answer("Выберите целевой маркетплейс:", reply_markup=platform_keyboard())
    await state.set_state(GeneratorStates.choosing_platform)

@router.callback_query(F.data.startswith("platform_"), GeneratorStates.choosing_platform)
async def platform_chosen(callback: Message, state: FSMContext):
    platform = "Wildberries" if callback.data == "platform_wb" else "Ozon"
    await state.update_data(platform=platform)
    await callback.message.edit_text(f"Выбран маркетплейс: **{platform}**\n\nВведите название вашего товара:")
    await state.set_state(GeneratorStates.entering_name)

@router.message(GeneratorStates.entering_name)
async def name_entered(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text)
    await message.answer("Отлично! Теперь отправьте краткие характеристики, особенности товара или ссылку на конкурента:")
    await state.set_state(GeneratorStates.entering_details)
    @router.message(GeneratorStates.entering_details)
async def details_entered(message: Message, state: FSMContext):
    user_data = await state.get_data()
    await state.clear()
    waiting_msg = await message.answer("🤖 *ИИ собирает поисковые ключи и генерирует текст... Подождите 5 секунд...*", parse_mode="Markdown")
    
    prompt = (
        f"Ты топовый копирайтер и эксперт по СНГ маркетплейсам. Напиши мощное продающее SEO описание товара для {user_data['platform']}.\n"
        f"Товар: {user_data['product_name']}\nХарактеристики/Входные данные: {message.text}\n\n"
        f"Выдай ответ строго разделенным по пунктам:\n"
        f"1) Продающий привлекательный текст (3-4 абзаца с пустыми строками между ними, без лишней воды).\n"
        f"2) Блок '🔥 КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА:' (выведи ровно 20 точных поисковых фраз через запятую).\n"
        f"3) Блок '💡 РЕКОМЕНДАЦИИ ПО ХАРАКТЕРИСТИКАМ:' (дай 3 точечных совета, какие параметры заполнить в ЛК продавца)."
    )
    
    try:
        response = requests.post(
            "https://pollinations.ai",
            json={"messages": [{"role": "user", "content": prompt}], "model": "openai"},
            timeout=30
        )
        generated_text = response.text
        
        await decrease_balance(message.from_user.id)
        new_balance = await get_user_balance(message.from_user.id)
        await waiting_msg.delete()
        
        await message.answer(
            f"✅ **Ваша SEO-карточка готова!**\n\n{generated_text}\n\n"
            f"📉 _Остаток генераций на балансе: {new_balance}_",
            reply_markup=main_keyboard(), parse_mode="Markdown"
        )
    except Exception as e:
        await waiting_msg.delete()
        await message.answer("❌ Нейросеть временно перегружена. Повторите попытку чуть позже.", reply_markup=main_keyboard())

@router.message(Command("give"))
async def give_balance(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: 
        return
    try:
        args = command.args.split()
        target_user = int(args[0])
        count = int(args[1])
        await add_balance_admin(target_user, count)
        await message.answer(f"✅ Баланс пользователя `{target_user}` пополнен на +{count}!")
        await bot.send_message(target_user, f"🎉 Баланс пополнен! Вам начислено **+{count} генераций**.")
    except:
        await message.answer("⚠️ Формат команды: `/give ID КОЛИЧЕСТВО`")

async def start_fake_server():
    port = int(os.getenv("PORT", 10000))
    server = await asyncio.start_server(lambda r, w: w.write(b"HTTP/1.1 200 OK\n\nBot is running!"), "0.0.0.0", port)
    async with server: 
        await server.serve_forever()

async def main():
    await init_db_pool()
    await asyncio.gather(
        dp.start_polling(bot),
        start_fake_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
        
