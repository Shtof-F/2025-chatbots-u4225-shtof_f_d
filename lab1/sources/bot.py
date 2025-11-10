"""
Telegram-бот для помощи команде
Функционал:
- Ответы на вопросы о компании/проекте/команде
- Хранение контактов коллег
- Напоминания о важных событиях
- Ежедневные дайджесты
"""

import os
import re
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    filters
)

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(ASKING_QUESTION, ADDING_CONTACT_NAME, ADDING_CONTACT_INFO,
 ADDING_EVENT_NAME, ADDING_EVENT_DATE, ADDING_EVENT_DESCRIPTION) = range(6)

# Имя базы данных
DB_NAME = 'bot_data.db'


class Database:
    """Класс для работы с базой данных SQLite"""
    
    def __init__(self, db_name: str = DB_NAME):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        """Получить соединение с базой данных"""
        try:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise
    
    def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Таблица с информацией о компании/проекте
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS company_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT UNIQUE,
                    answer TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица с контактами коллег
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    info TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица с событиями/напоминаниями
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    event_date TIMESTAMP NOT NULL,
                    description TEXT,
                    notified BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица с дайджестами
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("База данных инициализирована успешно")
        except sqlite3.Error as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise
    
    def add_company_info(self, question: str, answer: str):
        """Добавить информацию о компании/проекте"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO company_info (question, answer) VALUES (?, ?)',
                (question.lower(), answer)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления информации: {e}")
            return False
    
    def get_company_info(self, question: str) -> Optional[str]:
        """Получить информацию о компании/проекте"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT answer FROM company_info WHERE question = ?',
                (question.lower(),)
            )
            result = cursor.fetchone()
            conn.close()
            return result['answer'] if result else None
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения информации: {e}")
            return None
    
    def add_contact(self, name: str, info: str):
        """Добавить контакт коллеги"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO contacts (name, info) VALUES (?, ?)',
                (name, info)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления контакта: {e}")
            return False
    
    def get_contacts(self) -> List[Dict]:
        """Получить все контакты"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT name, info FROM contacts ORDER BY name')
            results = cursor.fetchall()
            conn.close()
            return [{'name': row['name'], 'info': row['info']} for row in results]
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения контактов: {e}")
            return []
    
    def search_contact(self, name: str) -> Optional[Dict]:
        """Найти контакт по имени"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT name, info FROM contacts WHERE name LIKE ?',
                (f'%{name}%',)
            )
            result = cursor.fetchone()
            conn.close()
            return {'name': result['name'], 'info': result['info']} if result else None
        except sqlite3.Error as e:
            logger.error(f"Ошибка поиска контакта: {e}")
            return None
    
    def add_event(self, name: str, event_date: datetime, description: str = ""):
        """Добавить событие/напоминание"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            # Сохраняем дату в ISO формате для правильного сравнения
            event_date_str = event_date.isoformat()
            cursor.execute(
                'INSERT INTO events (name, event_date, description) VALUES (?, ?, ?)',
                (name, event_date_str, description)
            )
            conn.commit()
            conn.close()
            logger.info(f"Событие '{name}' добавлено с датой {event_date_str}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления события: {e}")
            return False
    
    def get_upcoming_events(self, days: int = None) -> List[Dict]:
        """Получить предстоящие события
        
        Args:
            days: Количество дней вперед для поиска. Если None, возвращает все будущие события.
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            now = datetime.now()
            now_str = now.isoformat()
            
            if days is not None:
                end_date = now + timedelta(days=days)
                end_date_str = end_date.isoformat()
                cursor.execute(
                    '''SELECT name, event_date, description FROM events 
                       WHERE event_date >= ? AND event_date <= ? AND notified = 0
                       ORDER BY event_date''',
                    (now_str, end_date_str)
                )
            else:
                # Получить все будущие события
                cursor.execute(
                    '''SELECT name, event_date, description FROM events 
                       WHERE event_date >= ? AND notified = 0
                       ORDER BY event_date''',
                    (now_str,)
                )
            
            results = cursor.fetchall()
            conn.close()
            
            events = []
            for row in results:
                try:
                    event_date = datetime.fromisoformat(row['event_date'])
                    events.append({
                        'name': row['name'],
                        'event_date': event_date,
                        'description': row['description'] or ''
                    })
                except (ValueError, TypeError) as e:
                    logger.error(f"Ошибка парсинга даты события: {e}, дата: {row['event_date']}")
                    continue
            
            logger.info(f"Найдено {len(events)} событий из {len(results)} записей")
            return events
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения событий: {e}")
            return []
    
    def mark_event_notified(self, event_name: str, event_date: datetime):
        """Отметить событие как уведомленное"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            event_date_str = event_date.isoformat()
            cursor.execute(
                'UPDATE events SET notified = 1 WHERE name = ? AND event_date = ?',
                (event_name, event_date_str)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка обновления события: {e}")
            return False
    
    def add_digest(self, content: str):
        """Добавить дайджест"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('INSERT INTO digests (content) VALUES (?)', (content,))
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка добавления дайджеста: {e}")
            return False
    
    def get_recent_digests(self, limit: int = 5) -> List[str]:
        """Получить последние дайджесты"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT content FROM digests ORDER BY created_at DESC LIMIT ?',
                (limit,)
            )
            results = cursor.fetchall()
            conn.close()
            return [row['content'] for row in results]
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения дайджестов: {e}")
            return []


# Инициализация базы данных
db = Database()


async def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    try:
        welcome_message = """
👋 Привет! Я бот-помощник для команды.

Доступные команды:
/help - Показать справку
/question - Задать вопрос о компании/проекте
/answer - Добавить ответ на вопрос
/contacts - Показать все контакты
/add_contact - Добавить контакт коллеги
/find_contact - Найти контакт
/events - Показать предстоящие события
/add_event - Добавить событие/напоминание
/digest - Показать последние дайджесты
/add_digest - Добавить дайджест
        """
        await update.message.reply_text(welcome_message)
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")


async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help"""
    try:
        help_text = """
📚 Справка по командам:

🔍 Информация о компании/проекте:
/question - Задать вопрос
/answer - Добавить ответ на вопрос

👥 Контакты:
/contacts - Список всех контактов
/add_contact - Добавить новый контакт
/find_contact - Найти контакт по имени

📅 События:
/events - Предстоящие события (7 дней)
/add_event - Добавить новое событие

📰 Дайджесты:
/digest - Последние дайджесты
/add_digest - Добавить новый дайджест
        """
        await update.message.reply_text(help_text)
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")


async def question_start(update: Update, context: CallbackContext) -> int:
    """Начать диалог для вопроса"""
    try:
        await update.message.reply_text(
            "❓ Задайте ваш вопрос о компании/проекте/команде:"
        )
        return ASKING_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в question_start: {e}")
        return ConversationHandler.END


async def question_received(update: Update, context: CallbackContext) -> int:
    """Обработать полученный вопрос"""
    try:
        question = update.message.text
        answer = db.get_company_info(question)
        
        if answer:
            await update.message.reply_text(f"💡 Ответ:\n{answer}")
        else:
            await update.message.reply_text(
                "❌ К сожалению, я не знаю ответа на этот вопрос.\n"
                "Используйте /answer чтобы добавить ответ."
            )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в question_received: {e}")
        await update.message.reply_text("Произошла ошибка при обработке вопроса.")
        return ConversationHandler.END


async def answer_start(update: Update, context: CallbackContext) -> int:
    """Начать диалог для добавления ответа"""
    try:
        await update.message.reply_text(
            "📝 Введите вопрос и ответ в формате:\n"
            "Вопрос: ваш вопрос\n"
            "Ответ: ваш ответ"
        )
        return ASKING_QUESTION
    except Exception as e:
        logger.error(f"Ошибка в answer_start: {e}")
        return ConversationHandler.END


async def answer_received(update: Update, context: CallbackContext) -> int:
    """Обработать полученный ответ"""
    try:
        text = update.message.text
        text_lower = text.lower()
        
        # Проверяем наличие ключевых слов (независимо от регистра)
        if "вопрос" in text_lower and "ответ" in text_lower:
            # Ищем разделитель "ответ:" (case-insensitive)
            # Разделяем по "ответ:" независимо от регистра
            parts = re.split(r'ответ:\s*', text, flags=re.IGNORECASE, maxsplit=1)
            
            if len(parts) == 2:
                # Извлекаем вопрос (убираем "вопрос:" в начале)
                question_part = parts[0]
                question = re.sub(r'^.*?вопрос:\s*', '', question_part, flags=re.IGNORECASE).strip()
                answer = parts[1].strip()
                
                if question and answer:
                    if db.add_company_info(question, answer):
                        await update.message.reply_text("✅ Ответ успешно добавлен!")
                    else:
                        await update.message.reply_text("❌ Ошибка при добавлении ответа.")
                else:
                    await update.message.reply_text("❌ Вопрос и ответ не могут быть пустыми.")
            else:
                await update.message.reply_text("❌ Неверный формат. Попробуйте снова.")
        else:
            await update.message.reply_text("❌ Неверный формат. Используйте формат:\nВопрос: ...\nОтвет: ...")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в answer_received: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении ответа.")
        return ConversationHandler.END


async def cancel(update: Update, context: CallbackContext) -> int:
    """Отменить текущую операцию"""
    try:
        await update.message.reply_text("❌ Операция отменена.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в cancel: {e}")
        return ConversationHandler.END


async def show_contacts(update: Update, context: CallbackContext) -> None:
    """Показать все контакты"""
    try:
        contacts = db.get_contacts()
        if contacts:
            message = "👥 Контакты коллег:\n\n"
            for contact in contacts:
                message += f"👤 {contact['name']}\n"
                if contact['info']:
                    message += f"   {contact['info']}\n"
                message += "\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("📭 Контакты не найдены. Используйте /add_contact чтобы добавить.")
    except Exception as e:
        logger.error(f"Ошибка в show_contacts: {e}")
        await update.message.reply_text("Произошла ошибка при получении контактов.")


async def add_contact_start(update: Update, context: CallbackContext) -> int:
    """Начать добавление контакта"""
    try:
        await update.message.reply_text("👤 Введите имя коллеги:")
        return ADDING_CONTACT_NAME
    except Exception as e:
        logger.error(f"Ошибка в add_contact_start: {e}")
        return ConversationHandler.END


async def add_contact_name(update: Update, context: CallbackContext) -> int:
    """Сохранить имя контакта"""
    try:
        context.user_data['contact_name'] = update.message.text
        await update.message.reply_text("📝 Введите контактную информацию (телефон, email, должность и т.д.):")
        return ADDING_CONTACT_INFO
    except Exception as e:
        logger.error(f"Ошибка в add_contact_name: {e}")
        return ConversationHandler.END


async def add_contact_info(update: Update, context: CallbackContext) -> int:
    """Сохранить информацию о контакте"""
    try:
        name = context.user_data.get('contact_name')
        info = update.message.text
        
        if name and db.add_contact(name, info):
            await update.message.reply_text(f"✅ Контакт {name} успешно добавлен!")
            context.user_data.clear()
        else:
            await update.message.reply_text("❌ Ошибка при добавлении контакта.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в add_contact_info: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении контакта.")
        return ConversationHandler.END


async def find_contact(update: Update, context: CallbackContext) -> None:
    """Найти контакт по имени"""
    try:
        if not context.args:
            await update.message.reply_text("❌ Используйте: /find_contact <имя>")
            return
        
        search_name = " ".join(context.args)
        contact = db.search_contact(search_name)
        
        if contact:
            message = f"👤 {contact['name']}\n"
            if contact['info']:
                message += f"📝 {contact['info']}"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f"❌ Контакт '{search_name}' не найден.")
    except Exception as e:
        logger.error(f"Ошибка в find_contact: {e}")
        await update.message.reply_text("Произошла ошибка при поиске контакта.")


async def show_events(update: Update, context: CallbackContext) -> None:
    """Показать предстоящие события"""
    try:
        # Показываем все будущие события (без ограничения по дням)
        events = db.get_upcoming_events(days=None)
        if events:
            message = "📅 Предстоящие события:\n\n"
            for event in events:
                event_date = event['event_date']
                message += f"📌 {event['name']}\n"
                message += f"   📆 {event_date.strftime('%d.%m.%Y %H:%M')}\n"
                if event['description']:
                    message += f"   📝 {event['description']}\n"
                message += "\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("📭 Предстоящих событий не найдено.")
    except Exception as e:
        logger.error(f"Ошибка в show_events: {e}")
        await update.message.reply_text("Произошла ошибка при получении событий.")


async def add_event_start(update: Update, context: CallbackContext) -> int:
    """Начать добавление события"""
    try:
        await update.message.reply_text("📅 Введите название события:")
        return ADDING_EVENT_NAME
    except Exception as e:
        logger.error(f"Ошибка в add_event_start: {e}")
        return ConversationHandler.END


async def add_event_name(update: Update, context: CallbackContext) -> int:
    """Сохранить название события"""
    try:
        context.user_data['event_name'] = update.message.text
        await update.message.reply_text(
            "📆 Введите дату и время события в формате:\n"
            "ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 25.12.2024 15:00"
        )
        return ADDING_EVENT_DATE
    except Exception as e:
        logger.error(f"Ошибка в add_event_name: {e}")
        return ConversationHandler.END


async def add_event_date(update: Update, context: CallbackContext) -> int:
    """Сохранить дату события"""
    try:
        date_str = update.message.text
        try:
            event_date = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
            context.user_data['event_date'] = event_date
            await update.message.reply_text("📝 Введите описание события (или отправьте '-' чтобы пропустить):")
            return ADDING_EVENT_DESCRIPTION
        except ValueError:
            await update.message.reply_text("❌ Неверный формат даты. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")
            return ADDING_EVENT_DATE
    except Exception as e:
        logger.error(f"Ошибка в add_event_date: {e}")
        return ConversationHandler.END


async def add_event_description(update: Update, context: CallbackContext) -> int:
    """Сохранить описание события"""
    try:
        name = context.user_data.get('event_name')
        event_date = context.user_data.get('event_date')
        description = update.message.text if update.message.text != '-' else ""
        
        if name and event_date:
            if db.add_event(name, event_date, description):
                await update.message.reply_text(f"✅ Событие '{name}' успешно добавлено!")
                context.user_data.clear()
            else:
                await update.message.reply_text("❌ Ошибка при добавлении события.")
        else:
            await update.message.reply_text("❌ Ошибка: данные события не найдены.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в add_event_description: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении события.")
        return ConversationHandler.END


async def show_digest(update: Update, context: CallbackContext) -> None:
    """Показать последние дайджесты"""
    try:
        digests = db.get_recent_digests(5)
        if digests:
            message = "📰 Последние дайджесты:\n\n"
            for i, digest in enumerate(digests, 1):
                message += f"{i}. {digest}\n\n"
            await update.message.reply_text(message)
        else:
            await update.message.reply_text("📭 Дайджесты не найдены. Используйте /add_digest чтобы добавить.")
    except Exception as e:
        logger.error(f"Ошибка в show_digest: {e}")
        await update.message.reply_text("Произошла ошибка при получении дайджестов.")


async def add_digest_start(update: Update, context: CallbackContext) -> int:
    """Начать добавление дайджеста"""
    try:
        await update.message.reply_text("📰 Введите содержание дайджеста:")
        return ASKING_QUESTION  # Переиспользуем состояние
    except Exception as e:
        logger.error(f"Ошибка в add_digest_start: {e}")
        return ConversationHandler.END


async def add_digest_received(update: Update, context: CallbackContext) -> int:
    """Сохранить дайджест"""
    try:
        content = update.message.text
        if db.add_digest(content):
            await update.message.reply_text("✅ Дайджест успешно добавлен!")
        else:
            await update.message.reply_text("❌ Ошибка при добавлении дайджеста.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка в add_digest_received: {e}")
        await update.message.reply_text("Произошла ошибка при добавлении дайджеста.")
        return ConversationHandler.END


async def send_daily_digest(context: CallbackContext) -> None:
    """Отправка ежедневного дайджеста (задача по расписанию)"""
    try:
        # Получаем последний дайджест
        digests = db.get_recent_digests(1)
        if digests:
            message = f"📰 Ежедневный дайджест:\n\n{digests[0]}"
        else:
            message = "📰 Ежедневный дайджест:\n\nСегодня нет новых дайджестов."
        
        # Получаем предстоящие события на сегодня
        events = db.get_upcoming_events(1)
        if events:
            message += "\n\n📅 События на сегодня:\n"
            for event in events:
                message += f"• {event['name']}\n"
        
        # Отправляем всем пользователям (в реальном боте нужно хранить список chat_id)
        # Здесь просто логируем, так как нужен список пользователей
        logger.info(f"Ежедневный дайджест: {message}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке ежедневного дайджеста: {e}")


def main() -> None:
    """Основная функция запуска бота"""
    try:
        # Получение токена из переменных окружения
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN не установлен в переменных окружения")
        
        # Создание приложения
        application = Application.builder().token(token).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("contacts", show_contacts))
        application.add_handler(CommandHandler("find_contact", find_contact))
        application.add_handler(CommandHandler("events", show_events))
        application.add_handler(CommandHandler("digest", show_digest))
        
        # ConversationHandler для вопросов
        question_conv = ConversationHandler(
            entry_points=[CommandHandler("question", question_start)],
            states={
                ASKING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question_received)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(question_conv)
        
        # ConversationHandler для добавления ответов
        answer_conv = ConversationHandler(
            entry_points=[CommandHandler("answer", answer_start)],
            states={
                ASKING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_received)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(answer_conv)
        
        # ConversationHandler для добавления контактов
        contact_conv = ConversationHandler(
            entry_points=[CommandHandler("add_contact", add_contact_start)],
            states={
                ADDING_CONTACT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_contact_name)],
                ADDING_CONTACT_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_contact_info)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(contact_conv)
        
        # ConversationHandler для добавления событий
        event_conv = ConversationHandler(
            entry_points=[CommandHandler("add_event", add_event_start)],
            states={
                ADDING_EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_name)],
                ADDING_EVENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_date)],
                ADDING_EVENT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_description)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(event_conv)
        
        # ConversationHandler для добавления дайджестов
        digest_conv = ConversationHandler(
            entry_points=[CommandHandler("add_digest", add_digest_start)],
            states={
                ASKING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_digest_received)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        application.add_handler(digest_conv)
        
        # Настройка ежедневного дайджеста (отправка в 9:00 каждый день)
        # В реальном боте нужно добавить job_queue для расписания
        # application.job_queue.run_daily(send_daily_digest, time=datetime.time(hour=9, minute=0))
        
        logger.info("Бот запущен и готов к работе")
        
        # Запуск бота
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        raise


if __name__ == '__main__':
    main()

