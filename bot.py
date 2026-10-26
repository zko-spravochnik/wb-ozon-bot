import os
import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from anthropic import Anthropic

# ==================== ОБЯЗАТЕЛЬНЫЕ НАСТРОЙКИ АДМИНИСТРАТОРА ====================
# Впиши свои реальные данные между кавычками и вместо цифр:
TINKOFF_PHONE = "77058120376"  # Твой номер телефона, привязанный к Т-Банку (без плюса)
TINKOFF_CARD = "2200700942512566"   # Номер твоей карты Т-Банка (без пробелов)
ADMIN_ID = 8993374736           # Твой личный численный Telegram ID (который ты взял из @userinfobot)

# Считывание секретных ключей из настроек сервера Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Инициализация клиентов
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Пул подключений к БД Supabase
db_pool = None

async def init_db_pool():
    global db_pool
    # Подключение к Supabase с отключенным кэшем для стабильной работы пулера
    db_pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0, min_size=1, max_size=3)

# ==================== ФУНКЦИИ РАБОТЫ С СУПЕБЕЙЗ ====================
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

# ==================== СОСТОЯНИЯ (FSM) ====================
class GeneratorStates(StatesGroup):
    choosing_platform = State()
    entering_name = State()
    entering_details = State()

# ==================== ГЕНЕРАТОР ПЛАТЕЖНЫХ ССЫЛОК Т-БАНК ====================
def get_tinkoff_link(amount: int, user_id: int) -> str:
    # Создаем удобную прямую ссылку на перевод в Т-Банк с автоматическим комментарием ID
    comment = f"ID{user_id}"
    return f"https://tinkoff.ru{TINKOFF_PHONE}&card={TINKOFF_CARD}&amount={amount}&comment={comment}"

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✨ Создать описание")]],
        resize_keyboard=True
    )

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

# ==================== ХЕНДЛЕРЫ БОТА ====================

@router.message(Command("start"))
async def start_cmd(message: Message):
    balance = await get_user_balance(message.from_user.id)
    await message.answer(
        f"Привет, продавец! 👋\n\n"
        f"Я — автономный ИИ-генератор идеальных SEO-описаний карточек для Wildberries и Ozon.\n"
        f"Твой доступный баланс: **{balance} генераций**.\n\n"
        f"Нажми кнопку ниже, чтобы начать работу!",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

@router.message(F.text == "✨ Создать описание")
async def start_generation(message: Message, state: FSMContext):
    balance = await get_user_balance(message.from_user.id)
    if balance <= 0:
        await message.answer(
            "🛑 **Лимит бесплатных генераций исчерпан.**\n\n"
            "Чтобы продолжить выводить карточки в ТОП маркетплейсов, выберите подходящий пакет.\n\n"
            "Нажмите на нужный тариф — откроется официальная платежная форма Т-Банка. Оплатите её, "
            "и ваш баланс обновится после проверки администратором (в назначении платежа банк автоматически укажет ваш ID).",
            reply_markup=tariff_keyboard(message.from_user.id),
            parse_mode="Markdown"
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
    await message.answer(
        "Отлично! Теперь отправьте краткие характеристики, особенности товара или "
        "просто скопируйте текст/ссылку на аналогичный товар конкурента:"
    )
    await state.set_state(GeneratorStates.entering_details)

@router.message(GeneratorStates.entering_details)
async def details_entered(message: Message, state: FSMContext):
    user_data = await state.get_data()
    await state.clear()
    
    waiting_msg = await message.answer("🤖 *Claude сканирует ключи и собирает карточку... Подождите 3 секунды...*", parse_mode="Markdown")
    
    # Скрытый системный промпт для идеальной SEO-оптимизации карточек маркетплейсов
    system_prompt = (
        "Ты — топовый SEO-оптимизатор и копирайтер карточек товаров на СНГ маркетплейсах. "
        "Твоя цель — сделать текст, который заставит покупателя нажать 'Купить', а алгоритмы WB/Ozon выведут карточку на первую страницу.\n\n"
        "СТРОГИЙ РЕГЛАМЕНТ ОТВЕТА:\n"
        "1. Продающее описание (3-4 абзаца). Разделяй абзацы пустой строкой. Первое предложение должно сразу бить в боль клиента. "
        "Аккуратно, без переспама и «воды», вплетай в текст высокочастотные поисковые фразы, синонимы и LSI-ключи, релевантные товару.\n"
        "2. Блок поисковых тегов: Напиши заголовок '🔥 КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА:' и выведи 15-20 точных ключевых фраз через запятую.\n"
        "3. Инсайды для заполнения: Напиши заголовок '💡 РЕКОМЕНДАЦИИ ПО ХАРАКТЕРИСТИКАМ:' и дай 3 точечных совета, какие параметры (цвет, габариты, назначение) указать в доп. полях ЛК, чтобы расширить воронку категорий.\n\n"
        f"Маркетплейс: {user_data['platform']}\n"
        "Пиши исключительно на русском языке, профессионально и презентабельно."
    )
    
    user_input_content = f"Товар: {user_data['product_name']}\nВходные данные/Конкурент: {message.text}"

    try:
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input_content}]
        )
        
        generated_text = response.content.text
        await decrease_balance(message.from_user.id)
        new_balance = await get_user_balance(message.from_user.id)
        
        await waiting_msg.delete()
        await message.answer(
            f"✅ **Ваша SEO-карточка успешно сгенерирована!**\n\n{generated_text}\n\n"
            f"📉 _Остаток генераций: {new_balance}_",
            reply_markup=main_keyboard(),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await waiting_msg.delete()
        await message.answer(f"❌ Нейросеть временно занята. Повторите попытку. Ошибка: {str(e)}", reply_markup=main_keyboard())

# ==================== УЛЬТРА-УДОБНАЯ АДМИН-КОМАНДА ДЛЯ НАЧИСЛЕНИЯ БАЛАНСА КЛИКОМ ====================
@router.message(Command("give"))
async def give_balance(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        # Формат команды админа в чате бота: /give ТЕКУЩИЙ_USER_ID КОЛИЧЕСТВО
        args = command.args.split()
        target_user = int(args[0])
        count = int(args[1])
        
        await add_balance_admin(target_user, count)
        await message.answer(f"✅ Баланс пользователя `{target_user}` успешно пополнен на +{count} генераций!")
        
        # Автоматическое уведомление счастливому покупателю
        await bot.send_message(target_user, f"🎉 Баланс пополнен! Вам начислено **+{count} генераций**. Можете продолжать работу!")
    except Exception:
        await message.answer("⚠️ Ошибка. Неверный формат. Нужно писать так: `/give 123456789 10`")

# ==================== ЗАПУСК БОТА С ВЕБ-ПОРТОМ ДЛЯ RENDER ====================
async def start_fake_server():
    # Этот сервер нужен исключительно для того, чтобы бесплатный Render думал, что запущен сайт, и не выдавал ошибку портов
    import asyncio
    
    port = int(os.getenv("PORT", 10000))
    server = await asyncio.start_server(
        lambda r, w: w.write(b"HTTP/1.1 200 OK\n\nBot is running!"), 
        "0.0.0.0", 
        port
    )
    print(f"Виртуальный веб-сервер запущен на порту {port}")
    async with server:
        await server.serve_forever()

async def main():
    await init_db_pool()
    print("Пул Supabase успешно поднят. Бот запускается...")
    
    # Запускаем бота и веб-сервер одновременно в одном процессе
    await asyncio.gather(
        dp.start_polling(bot),
        start_fake_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
    
