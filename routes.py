# routes.py
from flask import Blueprint, render_template, request, redirect, jsonify, flash, current_app, abort, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
from models import User, Meal, Order, Allergy, Review, PurchaseRequest, Ingredient, MealIngredient, Product, WriteOff, \
    Notification, DeletionLog, FlexibleSubscription
from datetime import datetime, timedelta
import json
from collections import defaultdict
import os
from werkzeug.utils import secure_filename
import re
from functools import wraps
import threading
import time

routes = Blueprint('routes', __name__)

DAY_NAMES_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среду",
    "thursday": "четверг",
    "friday": "пятницу"
}


# Глобальная константа
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ УВЕДОМЛЕНИЙ ===

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ УДАЛЕНИЯ ===
def delete_notification(notification_id, user_id):
    """Удаляет одно уведомление"""
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if notification:
        db.session.delete(notification)
        db.session.commit()
        return True
    return False

def delete_all_notifications(user_id):
    """Удаляет все уведомления пользователя"""
    notifications = Notification.query.filter_by(user_id=user_id).all()
    for notification in notifications:
        db.session.delete(notification)
    db.session.commit()
    return True

def create_notification(user_id, title, message, type="info", order_id=None, request_id=None):
    """Создаёт уведомление для пользователя"""
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=type,
        order_id=order_id,
        request_id=request_id
    )
    db.session.add(notification)
    db.session.commit()
    return notification


def create_bulk_notifications(user_ids, title, message, type="info"):
    """Создаёт уведомления для нескольких пользователей"""
    for user_id in user_ids:
        create_notification(user_id, title, message, type)


def mark_notification_read(notification_id, user_id):
    """Отмечает уведомление как прочитанное"""
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if notification and not notification.is_read:
        notification.is_read = True
        db.session.commit()
        return True
    return False


def mark_all_notifications_read(user_id):
    """Отмечает все уведомления пользователя как прочитанные"""
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()


def get_unread_count(user_id):
    """Возвращает количество непрочитанных уведомлений"""
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def get_notifications(user_id, limit=20, offset=0):
    """Возвращает список уведомлений пользователя"""
    return Notification.query.filter_by(user_id=user_id) \
        .order_by(Notification.created_at.desc()) \
        .offset(offset).limit(limit).all()


def calculate_full_subscription_price():
    """Рассчитывает полную стоимость абонемента на основе текущих цен в меню."""
    total = 0.0
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    for day in days:
        for meal_type in ["breakfast", "lunch"]:
            meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
            if meal and meal.price:
                total += meal.price
    return total


def get_date_for_day(day_of_week, target_week_offset=0):
    """Возвращает дату для указанного дня недели с учётом смещения недели"""
    days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
    if day_of_week not in days_map:
        return datetime.today().date()

    today = datetime.today()
    current_weekday = today.weekday()

    # Если выходной (сб/вс) — считаем от следующего понедельника
    if current_weekday >= 5:
        # Начало следующей недели
        next_monday = today + timedelta(days=(7 - current_weekday))
        target_date = next_monday + timedelta(days=days_map[day_of_week])
    else:
        # Будний день — считаем от текущей недели
        diff = days_map[day_of_week] - current_weekday
        target_date = today + timedelta(days=diff)

    return target_date.date()


def role_required(required_role):
    """Декоратор для проверки роли пользователя"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect("/login")

            if current_user.role != required_role:
                flash("❌ У вас нет доступа к этой странице", "error")
                # Перенаправляем на свою панель
                if current_user.role == "student":
                    return redirect("/student")
                elif current_user.role == "cook":
                    return redirect("/cook")
                elif current_user.role == "admin":
                    return redirect("/admin")
                else:
                    return redirect("/")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def validate_password(password):
    """
    Валидация надежного пароля:
    - Минимум 8 символов
    - Хотя бы одна цифра
    - Хотя бы одна заглавная буква
    - Хотя бы одна строчная буква
    - Хотя бы один специальный символ
    Возвращает: (bool, str) - (успешно, сообщение об ошибке)
    """
    if len(password) < 8:
        return False, "Пароль должен содержать минимум 8 символов"

    if not re.search(r'\d', password):
        return False, "Пароль должен содержать хотя бы одну цифру"

    if not re.search(r'[A-Z]', password):
        return False, "Пароль должен содержать хотя бы одну заглавную букву"

    if not re.search(r'[a-z]', password):
        return False, "Пароль должен содержать хотя бы одну строчную букву"

    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=]', password):
        return False, "Пароль должен содержать хотя бы один специальный символ (!@#$%^&* и т.д.)"

    return True, ""


# === МАРШРУТЫ УВЕДОМЛЕНИЙ ===

@routes.route("/api/notifications/count")
@login_required
def get_notifications_count():
    """API: количество непрочитанных уведомлений"""
    count = get_unread_count(current_user.id)
    return jsonify({'count': count})


@routes.route("/api/notifications")
@login_required
def get_notifications_api():
    """API: список уведомлений"""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)

    notifications = get_notifications(current_user.id, limit, offset)
    return jsonify({
        'notifications': [n.to_dict() for n in notifications],
        'unread_count': get_unread_count(current_user.id)
    })


@routes.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read_api(notification_id):
    """API: отметить уведомление как прочитанное"""
    success = mark_notification_read(notification_id, current_user.id)
    return jsonify({'success': success})


@routes.route("/api/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read_api():
    """API: отметить все как прочитанные"""
    mark_all_notifications_read(current_user.id)
    return jsonify({'success': True})


@routes.route("/api/notifications/<int:notification_id>", methods=["DELETE"])
@login_required
def delete_notification_api(notification_id):
    """API: удалить одно уведомление"""
    success = delete_notification(notification_id, current_user.id)
    return jsonify({'success': success})

@routes.route("/api/notifications/delete-all", methods=["DELETE"])
@login_required
def delete_all_notifications_api():
    """API: удалить все уведомления"""
    delete_all_notifications(current_user.id)
    return jsonify({'success': True})


@routes.route("/notifications")
@login_required
def notifications_page():
    """Страница со всеми уведомлениями"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    notifications = Notification.query.filter_by(user_id=current_user.id) \
        .order_by(Notification.created_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    # Отмечаем все как прочитанные при открытии страницы
    mark_all_notifications_read(current_user.id)

    return render_template(
        "notifications.html",
        notifications=notifications.items,
        pagination=notifications
    )


# === ОСНОВНЫЕ МАРШРУТЫ ===

@routes.route("/", methods=["GET", "POST"])
def index():
    if current_user.is_authenticated:
        return redirect(f"/{current_user.role}")
    return redirect("/register")


@routes.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        class_name = request.form.get("class_name", "").strip()
        access_code = request.form.get("access_code", "").strip()

        if not full_name or not email or not password or role not in ["student", "cook", "admin"]:
            return render_template("register.html")

        # === ПРОВЕРКА СЕКРЕТНОГО КОДА ===
        correct_code = current_app.config['ACCESS_CODES'].get(role)
        if not correct_code:
            flash("Неверная роль пользователя", "error")
            return render_template("register.html")

        if access_code != correct_code:
            flash(f"❌ Неверный код доступа для роли '{role}'. Обратитесь к администратору для получения кода.", "error")
            return render_template("register.html")

        # Проверка класса для ученика
        if role == "student" and not class_name:
            flash("Поле 'Класс' обязательно для учеников", "error")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже существует", "error")
            return render_template("register.html")

        # После получения пароля
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            flash(error_msg, "error")
            return render_template("register.html")

        user = User(
            full_name=full_name,
            email=email,
            password=generate_password_hash(password),
            role=role,
            class_name=class_name if role == "student" else None
        )
        db.session.add(user)
        db.session.commit()

        create_notification(
            user_id=user.id,
            title="✅ Добро пожаловать!",
            message=f"Вы успешно зарегистрировались в системе школьного питания как {role}.",
            type="success"
        )
        return redirect("/login")
    return render_template("register.html")


@routes.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("login.html")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            # === ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: заблокированные аккаунты ===
            if not user.is_active:
                flash("❌ Ваш аккаунт заблокирован. Обратитесь к администратору.", "error")
                return render_template("login.html")

            login_user(user)

            create_notification(
                user_id=user.id,
                title="🔐 Вход в систему",
                message=f"Вы успешно вошли в систему. Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                type="info"
            )

            # Перенаправление в зависимости от роли
            if user.role == "student":
                return redirect("/student")
            elif user.role == "cook":
                return redirect("/cook")
            elif user.role == "admin":
                return redirect("/admin")
            else:
                return redirect("/")

        flash("❌ Неверный email или пароль", "error")
        return render_template("login.html")

    return render_template("login.html")


@routes.route("/student", methods=["GET", "POST"])
@login_required
def student():
    current_balance = current_user.balance
    if current_user.role != "student":
        return redirect("/")

    # === ПРАВИЛЬНЫЙ РАСЧЁТ ДАТ ДЛЯ ДНЕЙ НЕДЕЛИ ===
    today = datetime.now().date()
    current_weekday = today.weekday()  # 0=пн, 6=вс

    # === ФОРМИРОВАНИЕ СПИСКА ДОСТУПНЫХ ДНЕЙ ДЛЯ ОПЛАТЫ ===
    available_payment_days = []

    # Если выходной (сб или вс) - показываем дни следующей недели
    if current_weekday >= 5:  # 5=сб, 6=вс
        # Начало следующей недели (понедельник)
        next_monday = today + timedelta(days=(7 - current_weekday))
        for i in range(5):  # Только будни
            day_date = next_monday + timedelta(days=i)
            day_name_eng = ["monday", "tuesday", "wednesday", "thursday", "friday"][i]
            day_name_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"][i]
            available_payment_days.append({
                'value': day_name_eng,
                'display': f"{day_name_ru} ({day_date.strftime('%d.%m')})"
            })
    # Если будний день - показываем оставшиеся дни текущей недели
    else:
        # Начало текущей недели (понедельник)
        monday = today - timedelta(days=current_weekday)
        for i in range(current_weekday, 5):  # С сегодняшнего до пятницы
            day_date = monday + timedelta(days=i)
            day_name_eng = ["monday", "tuesday", "wednesday", "thursday", "friday"][i]
            day_name_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"][i]
            available_payment_days.append({
                'value': day_name_eng,
                'display': f"{day_name_ru} ({day_date.strftime('%d.%m')})"
            })
    monday = today - timedelta(days=today.weekday())
    day_dates = {
        'monday': monday,
        'tuesday': monday + timedelta(days=1),
        'wednesday': monday + timedelta(days=2),
        'thursday': monday + timedelta(days=3),
        'friday': monday + timedelta(days=4),
        'saturday': monday + timedelta(days=5),
        'sunday': monday + timedelta(days=6)
    }

    # === ДОБАВЛЯЕМ ВЫЧИСЛЕНИЕ ДИАПАЗОНА НЕДЕЛИ ===
    start_of_week = monday
    end_of_week = start_of_week + timedelta(days=6)
    current_week_range = f"{start_of_week.strftime('%d %b').replace('Jan', 'янв').replace('Feb', 'фев').replace('Mar', 'мар').replace('Apr', 'апр').replace('May', 'мая').replace('Jun', 'июн').replace('Jul', 'июл').replace('Aug', 'авг').replace('Sep', 'сен').replace('Oct', 'окт').replace('Nov', 'ноя').replace('Dec', 'дек')} - {end_of_week.strftime('%d %b').replace('Jan', 'янв').replace('Feb', 'фев').replace('Mar', 'мар').replace('Apr', 'апр').replace('May', 'мая').replace('Jun', 'июн').replace('Jul', 'июл').replace('Aug', 'авг').replace('Sep', 'сен').replace('Oct', 'окт').replace('Nov', 'ноя').replace('Dec', 'дек')}"

    allergy_record = Allergy.query.filter_by(student_id=current_user.id).first()
    current_allergy = allergy_record.text if allergy_record else ""

    if request.method == "POST":
        allergy_text = request.form.get("allergy", "").strip()
        if allergy_record:
            allergy_record.text = allergy_text
        else:
            if allergy_text:
                db.session.add(Allergy(student_id=current_user.id, text=allergy_text))
        db.session.commit()
        create_notification(
            user_id=current_user.id,
            title="⚠️ Пищевые особенности обновлены",
            message=f"Ваши пищевые особенности были {'обновлены' if allergy_record else 'добавлены'}.",
            type="info"
        )
        return redirect("/student")

    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_names = {d: n for d, n in
                 zip(days, ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"])}

    today = datetime.today().weekday()
    day_index_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"}
    current_day = day_index_map.get(today, None)

    # === ЗАГРУЗКА МЕНЮ С ИНГРЕДИЕНТАМИ ===
    meals = {day: {"breakfast": None, "lunch": None} for day in days}
    for m in Meal.query.all():
        if m.day_of_week in meals and m.meal_type in meals[m.day_of_week]:
            # Загружаем ингредиенты для блюда
            ingredients = []
            for mi in MealIngredient.query.filter_by(meal_id=m.id).all():
                ing = db.session.get(Ingredient, mi.ingredient_id)
                if ing:
                    ingredients.append({
                        'name': ing.name,
                        'quantity': mi.quantity,
                        'unit': mi.unit
                    })
            meals[m.day_of_week][m.meal_type] = {
                "name": m.name,
                "price": m.price,
                "ingredients": ingredients  # ← КЛЮЧЕВОЕ ДОБАВЛЕНИЕ
            }

    # === СОБИРАЕМ ОТЗЫВЫ С ПРИВЯЗКОЙ К НЕДЕЛЕ ===
    user_reviews_current = {}  # Только для текущей недели (неделя 0) для начального отображения
    user_reviews_all = {}  # Все отзывы со строковыми ключами для JavaScript
    # === ВЫЧИСЛЯЕМ АБСОЛЮТНЫЙ НОМЕР ТЕКУЩЕЙ НЕДЕЛИ ===
    current_iso_year, current_iso_week, _ = datetime.now().date().isocalendar()

    for r in Review.query.filter_by(student_id=current_user.id).all():
        # Для начального отображения (текущая неделя = 0)
        if r.review_year == current_iso_year and r.review_week_iso == current_iso_week:
            user_reviews_current[(r.day_of_week, r.meal_type)] = r.text

        # === ИСПРАВЛЕНИЕ: Ключ на основе абсолютных значений ===
        # Поддержка старых отзывов без review_year/review_week_iso
        if hasattr(r, 'review_year') and r.review_year and hasattr(r, 'review_week_iso') and r.review_week_iso:
            key = f"{r.day_of_week}_{r.meal_type}_{r.review_year}_{r.review_week_iso}"
        else:
            # Для старых отзывов используем week_number (обратная совместимость)
            key = f"{r.day_of_week}_{r.meal_type}_{r.week_number}"
        user_reviews_all[key] = r.text

    orders = Order.query.filter_by(student_id=current_user.id).all()

    # === Расчёт стоимости абонемента (только будни) ===
    today_weekday = datetime.today().weekday()
    if today_weekday <= 4:
        remaining_days = ["monday", "tuesday", "wednesday", "thursday", "friday"][today_weekday:]
        full_subscription_price = 0.0
        for day in remaining_days:
            for mt in ["breakfast", "lunch"]:
                meal = Meal.query.filter_by(day_of_week=day, meal_type=mt).first()
                if meal and meal.price:
                    full_subscription_price += meal.price
    else:
        full_subscription_price = 0.0

    paid_sum = 0.0
    for order in orders:
        if order.status == "paid" and order.paid_at is not None:
            if today_weekday <= 4:
                try:
                    day_index = ["monday", "tuesday", "wednesday", "thursday", "friday"].index(order.day_of_week)
                    if day_index >= today_weekday:
                        meal = Meal.query.filter_by(day_of_week=order.day_of_week, meal_type=order.meal_type).first()
                        if meal and meal.price:
                            paid_sum += meal.price
                except ValueError:
                    pass

    remaining_subscription_price = max(0.0, full_subscription_price - paid_sum)

    # === Расчёт статусов оплаты с привязкой к неделям ===
    order_status = {}
    paid_keys_simple = []

    all_orders = Order.query.filter_by(student_id=current_user.id).all()

    for o in all_orders:
        if o.serving_date:
            serving_week = o.serving_date.isocalendar()[1]
            current_week = datetime.now().date().isocalendar()[1]
            week_offset = serving_week - current_week

            # Показываем статусы для текущей и ближайших 3 недель
            if -52 <= week_offset <= 52:
                key = f"{o.day_of_week}_{o.meal_type}_{week_offset}"
                order_status[key] = {
                    'paid': o.status == 'paid',
                    'consumed': o.is_collected,
                    'student_confirmed': o.student_confirmed,  # ученик подтвердил
                    'date': o.serving_date.strftime('%d.%m.%Y'),
                    'order_id': o.id  # для кнопки подтверждения
                }

            # Для простой проверки оплаты (без привязки к неделе)
            if o.status == 'paid' and o.paid_at is not None:
                paid_keys_simple.append(f"{o.day_of_week}_{o.meal_type}")

    paid_count = len([o for o in orders if o.status == "paid" and o.paid_at is not None])
    consumed_count = len([o for o in orders if o.is_collected])
    total_possible = 10

    return render_template(
        "student.html",
        days=days,
        day_names=day_names,
        meals=meals,
        current_allergy=current_allergy,
        order_status=order_status,
        paid_count=paid_count,
        consumed_count=consumed_count,
        total_possible=total_possible,
        current_balance=current_balance,
        full_subscription_price=full_subscription_price,
        paid_sum=paid_sum,
        remaining_subscription_price=remaining_subscription_price,
        current_day=current_day,
        day_dates=day_dates,
        paid_keys_simple=paid_keys_simple,
        current_week_range=current_week_range,
        user_reviews=user_reviews_current,  # Для начального отображения
        user_reviews_all=user_reviews_all,
        available_payment_days=available_payment_days
    )


@routes.route("/submit_review", methods=["POST"])
@login_required
def submit_review():
    if current_user.role != "student":
        return redirect("/")

    day = request.form.get("day")
    meal_type = request.form.get("meal_type")
    text = request.form.get("text", "").strip()
    week_offset_str = request.form.get("week_offset", "0")

    try:
        week_offset = int(week_offset_str)
    except (ValueError, TypeError):
        week_offset = 0

    # === КРИТИЧЕСКАЯ ПРОВЕРКА: нельзя оставлять отзыв на будущий день ===
    today = datetime.today().date()
    monday_this_week = today - timedelta(days=today.weekday())
    monday_review_week = monday_this_week + timedelta(weeks=week_offset)

    # Карта дней недели
    day_index_map = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2,
        'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
    }
    day_offset = day_index_map.get(day, 0)
    review_date = monday_review_week + timedelta(days=day_offset)

    if review_date > today:
        flash("❌ Нельзя оставлять отзыв на будущий день. Дождитесь наступления этого дня.", "error")
        return redirect("/student")

    # === КРИТИЧЕСКАЯ ПРОВЕРКА: заказ должен быть оплачен И получен ===
    # Ищем заказ на конкретный день
    serving_date = review_date

    order = Order.query.filter_by(
        student_id=current_user.id,
        day_of_week=day,
        meal_type=meal_type,
        serving_date=serving_date
    ).first()

    # Проверяем статус заказа
    if not order:
        flash("❌ Нельзя оставить отзыв без заказа. Сначала оплатите питание.", "error")
        return redirect("/student")

    # === ИСПРАВЛЕНИЕ: если заказ уже выдан или подтверждён — статус не важен ===
    if not order.is_collected and not order.student_confirmed:
        # Если заказ ещё не выдан и не подтверждён, проверяем оплату
        if order.status != "paid":
            flash("❌ Заказ не оплачен. Сначала оплатите питание, чтобы оставить отзыв.", "error")
            return redirect("/student")
    else:
        # Если заказ выдан или подтверждён — отзыв можно оставить
        # (даже если статус был изменён на 'cancelled' после выдачи)
        pass

    if not order.is_collected:
        flash("❌ Питание ещё не выдано поваром. Обратитесь в столовую.", "error")
        return redirect("/student")

    if not order.student_confirmed:
        flash("❌ Вы ещё не подтвердили получение питания. Нажмите кнопку 'Подтвердить получение' в вашем кабинете.",
              "error")
        return redirect("/student")

    # === ВЫЧИСЛЯЕМ АБСОЛЮТНЫЙ НОМЕР НЕДЕЛИ И ГОД ===
    iso_year, iso_week, _ = monday_review_week.isocalendar()

    if day and meal_type and text:
        # Ищем отзыв по АБСОЛЮТНЫМ параметрам (не по смещению!)
        existing = Review.query.filter_by(
            student_id=current_user.id,
            day_of_week=day,
            meal_type=meal_type,
            review_year=iso_year,
            review_week_iso=iso_week
        ).first()

        if existing:
            existing.text = text
            existing.timestamp = datetime.utcnow()
            # Обновляем старое поле для совместимости
            existing.week_number = week_offset
            # Обновляем абсолютные значения (на случай если неделя изменилась)
            existing.review_year = iso_year
            existing.review_week_iso = iso_week
        else:
            db.session.add(Review(
                student_id=current_user.id,
                day_of_week=day,
                meal_type=meal_type,
                text=text,
                week_number=week_offset,  # для обратной совместимости
                review_year=iso_year,
                review_week_iso=iso_week
            ))

        db.session.commit()
        create_notification(
            user_id=current_user.id,
            title="📝 Отзыв отправлен",
            message=f"Ваш отзыв на {'завтрак' if meal_type == 'breakfast' else 'обед'} на {DAY_NAMES_RU[day]} успешно отправлен.",
            type="success"
        )

    return redirect("/student")


@routes.route("/pay", methods=["POST"])
@login_required
def pay():
    if current_user.role != "student":
        return redirect("/student")

    payment_type = request.form.get("type")
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    meal_types = ["breakfast", "lunch"]

    # Получаем все заказы ученика
    all_orders = Order.query.filter_by(student_id=current_user.id).all()
    paid_orders = [o for o in all_orders if o.status == "paid" and o.paid_at is not None]
    paid_keys = {(o.day_of_week, o.meal_type) for o in paid_orders}

    # === Проверка: всё уже оплачено? ===
    all_possible = {(d, mt) for d in days for mt in meal_types}
    if paid_keys == all_possible:
        flash("Все приёмы уже оплачены!", "error")
        return redirect("/student")

    # === Разовая оплата ===
    if payment_type == "single":
        day = request.form.get("day")
        meal_type = request.form.get("meal_type")

        if day not in days or meal_type not in meal_types:
            flash("Неверные данные для оплаты.", "error")
            return redirect("/student")

        if (day, meal_type) in paid_keys:
            flash(f"{'Завтрак' if meal_type == 'breakfast' else 'Обед'} на {DAY_NAMES_RU[day]} уже оплачен.", "error")
            return redirect("/student")

        meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
        if not meal:
            flash("Меню не найдено.", "error")
            return redirect("/student")

        total_price = meal.price

        if current_user.balance < total_price:
            flash(f"Недостаточно средств! Требуется {total_price} ₽, доступно: {current_user.balance} ₽", "error")
            return redirect("/student")

        # === Собираем ингредиенты на момент оплаты ===
        ingredients_list = []
        for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
            ing = db.session.get(Ingredient, mi.ingredient_id)
            if ing:
                ingredients_list.append({
                    "name": ing.name,
                    "qty": mi.quantity,
                    "unit": mi.unit
                })

        # Создаём заказ с фиксацией данных
        serving_date = get_date_for_day(day)
        order = Order(
            student_id=current_user.id,
            day_of_week=day,
            meal_type=meal_type,
            serving_date=serving_date,
            status="paid",
            paid_at=datetime.utcnow(),
            meal_name=meal.name,
            meal_price=meal.price,
            meal_ingredients=json.dumps(ingredients_list, ensure_ascii=False),
            payment_source='single'  # ← РАЗОВАЯ ОПЛАТА
        )
        db.session.add(order)

        current_user.balance -= total_price

        db.session.commit()

        # === УВЕДОМЛЕНИЕ УЧЕНИКУ ===
        create_notification(
            user_id=current_user.id,
            title="✅ Оплата прошла успешно",
            message=f"{'Завтрак' if meal_type == 'breakfast' else 'Обед'} на {DAY_NAMES_RU[day]} оплачен. Сумма: {total_price} ₽",
            type="success",
            order_id=order.id
        )

        flash(f"{'Завтрак' if meal_type == 'breakfast' else 'Обед'} на {DAY_NAMES_RU[day]} оплачен!", "success")
        return redirect("/student")

    # === Абонемент (только на оставшиеся дни) ===
    elif payment_type == "subscription":
        if current_user.has_subscription:
            flash("Абонемент уже оплачен!", "error")
            return redirect("/student")

        # Определяем текущий день недели (0=понедельник, 4=пятница)
        today_weekday = datetime.today().weekday()
        if today_weekday > 4:  # выходные — абонемент не нужен
            flash("Абонемент недоступен в выходные дни.", "error")
            return redirect("/student")

        # Дни с сегодняшнего по пятницу
        remaining_days = ["monday", "tuesday", "wednesday", "thursday", "friday"][today_weekday:]
        meal_types = ["breakfast", "lunch"]

        # Собираем неплаченные приёмы
        unpaid_keys = []
        for day in remaining_days:
            for mt in meal_types:
                if (day, mt) not in paid_keys:
                    unpaid_keys.append((day, mt))

        if not unpaid_keys:
            flash("Все оставшиеся приёмы уже оплачены!", "error")
            return redirect("/student")

        # Рассчитываем стоимость
        total_price = 0.0
        meals_to_create = []
        for day, mt in unpaid_keys:
            meal = Meal.query.filter_by(day_of_week=day, meal_type=mt).first()
            price = meal.price if meal and meal.price else 0.0
            total_price += price
            meals_to_create.append((day, mt))

        if current_user.balance < total_price:
            flash(f"Недостаточно средств! Требуется {total_price:.2f} ₽, доступно: {current_user.balance} ₽", "error")
            return redirect("/student")

        # Создаём заказы с фиксацией рецепта
        for day, mt in meals_to_create:
            meal = Meal.query.filter_by(day_of_week=day, meal_type=mt).first()
            if not meal:
                continue  # пропускаем, если меню отсутствует

            # Собираем ингредиенты
            ingredients_list = []
            for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
                ing = db.session.get(Ingredient, mi.ingredient_id)
                if ing:
                    ingredients_list.append({
                        "name": ing.name,
                        "qty": mi.quantity,
                        "unit": mi.unit
                    })

            serving_date = get_date_for_day(day)
            db.session.add(Order(
                student_id=current_user.id,
                day_of_week=day,
                meal_type=mt,
                serving_date=serving_date,
                status="paid",
                paid_at=datetime.utcnow(),
                meal_name=meal.name,
                meal_price=meal.price,
                meal_ingredients=json.dumps(ingredients_list, ensure_ascii=False)
            ))

        current_user.balance -= total_price
        current_user.has_subscription = True  # ← помечаем, что абонемент куплен

        db.session.commit()

        # === УВЕДОМЛЕНИЕ УЧЕНИКУ ===
        create_notification(
            user_id=current_user.id,
            title="✅ Абонемент оплачен",
            message=f"Абонемент на оставшиеся дни успешно оплачен! Сумма: {total_price:.2f} ₽",
            type="success"
        )

        if len(unpaid_keys) == len(remaining_days) * 2:
            flash(f"Абонемент на оставшиеся дни ({len(remaining_days)}) успешно оплачен!", "success")
        else:
            flash(f"Абонемент на оставшиеся приёмы оплачен! Списано: {total_price:.2f} ₽", "success")
        return redirect("/student")

    else:
        flash("Неверный тип оплаты.", "error")
        return redirect("/student")


@routes.route("/topup", methods=["POST"])
@login_required
def topup():
    if current_user.role != "student":
        return redirect("/student")

    try:
        amount = float(request.form.get("amount", 0))
        if amount > 0 and amount <= 10000:  # ограничение на разумную сумму
            current_user.balance += amount
            db.session.commit()

            # === УВЕДОМЛЕНИЕ О ПОПОЛНЕНИИ ===
            create_notification(
                user_id=current_user.id,
                title="💰 Баланс пополнен",
                message=f"Ваш баланс пополнен на {amount} ₽. Текущий баланс: {current_user.balance:.2f} ₽",
                type="success"
            )
    except (ValueError, TypeError):
        pass

    return redirect("/student")


@routes.route("/cook", methods=["GET"])
@login_required
def cook():
    if current_user.role != "cook":
        return redirect("/")

    today = datetime.today().date()

    # === ИЗМЕНЕНИЕ: показываем только заказы на сегодня ===
    pending_orders = Order.query.filter(
        Order.is_collected == False,
        Order.status == "paid",
        Order.serving_date == today  # ← ФИЛЬТР ПО ДАТЕ
    ).all()

    completed_orders = Order.query.filter(
        Order.is_collected == True,
        Order.serving_date == today  # ← ФИЛЬТР ПО ДАТЕ
    ).all()

    # === Список учеников с заказами ===
    students_dict = {s.id: s for s in User.query.filter_by(role="student").all()}
    allergies_dict = {}
    for s in students_dict.values():
        allergy_rec = Allergy.query.filter_by(student_id=s.id).first()
        allergies_dict[s.id] = allergy_rec.text.strip() if allergy_rec and allergy_rec.text.strip() else None

    review_cache = {(r.student_id, r.day_of_week, r.meal_type): r for r in Review.query.all()}

    students_data = {}
    for order in Order.query.order_by(Order.serving_date, Order.meal_type).all():
        if order.student_id not in students_dict:
            continue

        student = students_dict[order.student_id]
        if student.id not in students_data:
            students_data[student.id] = {
                'student': student,
                'allergy': allergies_dict.get(student.id),
                'pending': [],
                'completed': []
            }

        entry = {
            'order': order,
            'review': review_cache.get((order.student_id, order.day_of_week, order.meal_type))
        }

        # === КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: проверяем статус оплаты ===
        if order.is_collected:
            # Завершенные заказы тоже должны быть оплачены
            if order.status == 'paid':
                students_data[student.id]['completed'].append(entry)
        else:
            # Только оплаченные заказы добавляем в ожидающие
            if order.status == 'paid':
                students_data[student.id]['pending'].append(entry)

    sorted_students = sorted(students_data.values(), key=lambda x: x['student'].full_name)

    # === Расчёт потребности и остатков ===
    total_students = len(students_dict)
    need_and_stock = []

    if total_students > 0:
        # Агрегируем потребность по ингредиентам
        ingredient_needs = db.session.query(
            Ingredient.id,
            Ingredient.name,
            MealIngredient.unit,
            db.func.sum(MealIngredient.quantity * total_students).label('needed')
        ).join(MealIngredient, Ingredient.id == MealIngredient.ingredient_id) \
            .group_by(Ingredient.id, Ingredient.name, MealIngredient.unit) \
            .all()

        # Получаем текущие остатки
        stock_map = {p.ingredient_id: p for p in Product.query.all()}

        for ing_id, name, unit, needed in ingredient_needs:
            product = stock_map.get(ing_id)
            current = product.quantity if product else 0.0

            need_and_stock.append({
                'name': name,
                'needed': float(needed),
                'current': float(current),
                'unit': unit,
                'deficit': max(0.0, float(needed) - float(current))
            })

    # Сортируем по дефициту (сначала самые критичные)
    need_and_stock.sort(key=lambda x: x['deficit'], reverse=True)

    # === ПРОВЕРКА КРИТИЧЕСКОГО ДЕФИЦИТА ===
    critical_deficit = [item for item in need_and_stock if
                        item['deficit'] > 0 and item['current'] < item['needed'] * 0.3]

    if critical_deficit:
        # Проверяем, не отправляли ли уже уведомление сегодня
        today = datetime.utcnow().date()
        existing = Notification.query.filter(
            Notification.user_id == current_user.id,
            Notification.type == "warning",
            Notification.created_at >= datetime.combine(today, datetime.min.time()),
            Notification.title.like("%Критический дефицит%")
        ).first()

        if not existing:
            deficit_list = ", ".join([f"{item['name']}" for item in critical_deficit[:5]])
            create_notification(
                user_id=current_user.id,
                title="⚠️ Критический дефицит продуктов",
                message=f"Низкие остатки: {deficit_list}. Необходимо срочно оформить заявку на закупку!",
                type="warning"
            )

    # === Ингредиенты для выпадающего списка корзины (ТОЛЬКО используемые в меню) ===
    used_ingredient_ids = db.session.query(MealIngredient.ingredient_id).distinct().all()
    used_ids = {id[0] for id in used_ingredient_ids}
    all_ingredients = Ingredient.query.filter(Ingredient.id.in_(used_ids)).order_by(Ingredient.name).all()

    for ing in all_ingredients:
        if ing.name in ["Яйца", "Булочка", "Печенье", "Тосты", "Батончик мюсли", "Чай", "Сок", "Компот (сухофрукты)",
                        "Кисель"]:
            ing.default_unit = "шт"
        elif "молоко" in ing.name.lower() or "вода" in ing.name.lower() or "сок" in ing.name.lower():
            ing.default_unit = "мл"
        else:
            ing.default_unit = "г"

    # === Журнал списаний ===
    write_offs = WriteOff.query.filter_by(cook_id=current_user.id) \
        .order_by(WriteOff.created_at.desc()) \
        .limit(20).all()

    return render_template(
        "cook.html",
        students=sorted_students,
        total_students=total_students,
        all_ingredients=all_ingredients,
        need_and_stock=need_and_stock,  # ← передаём данные о запасах
        write_offs=write_offs,
        today=datetime.today().date()
    )


@routes.route("/request_product", methods=["POST"])
@login_required
def request_product():
    if current_user.role != "cook":
        return redirect("/cook")

    ingredient_id = request.form.get("ingredient_id")
    quantity = request.form.get("quantity", type=float)
    unit = request.form.get("unit", "г")

    if not ingredient_id or not quantity or quantity <= 0:
        return redirect("/cook")

    ingredient = db.session.get(Ingredient, ingredient_id)
    if not ingredient:
        return redirect("/cook")

    db.session.add(PurchaseRequest(
        cook_id=current_user.id,
        product=ingredient.name,
        quantity=quantity,
        unit=unit,
        status="pending"
    ))
    db.session.commit()

    # === УВЕДОМЛЕНИЯ АДМИНИСТРАТОРАМ ===
    admin_users = User.query.filter_by(role="admin").all()
    admin_ids = [admin.id for admin in admin_users]

    create_bulk_notifications(
        admin_ids,
        title="📦 Новая заявка на закупку",
        message=f"Повар {current_user.full_name} отправил заявку на закупку: {ingredient.name} — {quantity} {unit}",
        type="info"
    )

    return redirect("/cook")


@routes.route("/cook/mark_collected", methods=["POST"])
@login_required
def mark_collected():
    if current_user.role != "cook":
        return redirect("/")

    order_id = request.form.get("order_id")
    order = Order.query.get(order_id)
    if not order:
        flash("Заказ не найден", "error")
        return redirect("/cook")

    # === ПРОВЕРКА: можно выдавать только сегодняшние заказы ===
    today = datetime.today().date()
    if order.serving_date != today:
        flash(f"Можно выдавать заказы только в день их назначения. "
              f"Заказ на {order.serving_date.strftime('%d.%m.%Y')}", "error")
        return redirect("/cook")

    # Проверка: заказ должен быть оплачен
    if order.status != "paid":
        flash("Заказ не оплачен", "error")
        return redirect("/cook")

    # === ПРОВЕРКА НАЛИЧИЯ ИНГРЕДИЕНТОВ ===
    try:
        ingredients_used = json.loads(order.meal_ingredients)
    except:
        # Если нет зафиксированных ингредиентов - загружаем из меню
        meal = Meal.query.filter_by(
            day_of_week=order.day_of_week,
            meal_type=order.meal_type
        ).first()
        if not meal:
            flash("Блюдо не найдено в меню. Выдача невозможна.", "error")
            return redirect("/cook")

        ingredients_used = []
        for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
            ing = db.session.get(Ingredient, mi.ingredient_id)
            if ing:
                ingredients_used.append({
                    "name": ing.name,
                    "qty": mi.quantity,
                    "unit": mi.unit
                })

    # Проверяем наличие каждого ингредиента на складе
    insufficient = []
    for item in ingredients_used:
        ingredient = Ingredient.query.filter_by(name=item["name"]).first()
        if not ingredient:
            insufficient.append(f"{item['name']} (ингредиент не найден)")
            continue

        product = Product.query.filter_by(ingredient_id=ingredient.id).first()
        needed_qty = float(item["qty"])

        if not product or product.quantity < needed_qty:
            current_qty = product.quantity if product else 0
            insufficient.append(
                f"{item['name']} (нужно {needed_qty}{item['unit']}, есть {current_qty}{item['unit']})"
            )

    # === ЕСЛИ ЧЕГО-ТО НЕ ХВАТАЕТ - НЕ ВЫДАВАТЬ! ===
    if insufficient:
        error_msg = "❌ Недостаточно продуктов для выдачи:\n" + "\n".join(insufficient)
        flash(error_msg, "error")
        return redirect("/cook")

    # === ВСЁ ЕСТЬ - СПИСЫВАЕМ ИНГРЕДИЕНТЫ ===
    for item in ingredients_used:
        ingredient = Ingredient.query.filter_by(name=item["name"]).first()
        if ingredient:
            product = Product.query.filter_by(ingredient_id=ingredient.id).first()
            if product:
                product.quantity -= float(item["qty"])

    # Отмечаем заказ как выданный
    order.is_collected = True
    order.consumed_at = datetime.utcnow()
    db.session.commit()

    # Уведомление ученику - ПРОСИМ ПОДТВЕРДИТЬ
    create_notification(
        user_id=order.student_id,
        title="🍽️ Питание выдано",
        message=f"{'Завтрак' if order.meal_type == 'breakfast' else 'Обед'} на {DAY_NAMES_RU.get(order.day_of_week, order.day_of_week)} выдан в столовой. Пожалуйста, подтвердите получение в вашем кабинете.",
        type="info",
        order_id=order.id
    )

    flash("✅ Заказ успешно выдан! Ученик должен подтвердить получение.", "success")
    return redirect("/cook")


@routes.route("/cook/submit_bulk_request", methods=["POST"])
@login_required
def submit_bulk_request():
    if current_user.role != "cook":
        return jsonify({"error": "Доступ запрещён"}), 403

    try:
        requests_data = request.get_json()
        if not isinstance(requests_data, list):
            return jsonify({"error": "Неверный формат данных"}), 400

        # Получаем администраторов
        admin_users = User.query.filter_by(role="admin").all()
        admin_ids = [admin.id for admin in admin_users]

        # Обработка заявок
        for item in requests_data:
            product_name = item.get("product", "").strip()
            quantity_str = item.get("quantity", "0")
            unit = item.get("unit", "г").strip()

            # Безопасное преобразование количества
            try:
                quantity = float(quantity_str)
                if quantity <= 0:
                    continue
            except (TypeError, ValueError):
                continue

            if not product_name:
                continue

            full_product_name = f"{product_name} ({unit})" if unit else product_name

            # Создаём заявку
            request_obj = PurchaseRequest(
                cook_id=current_user.id,
                product=full_product_name,
                quantity=quantity,
                unit=unit,
                status="pending"
            )
            db.session.add(request_obj)
            db.session.flush()  # Получаем ID

            # Отправляем уведомления администраторам
            for admin_id in admin_ids:
                create_notification(
                    user_id=admin_id,
                    title="📦 Новая заявка на закупку",
                    message=f"Повар {current_user.full_name} отправил заявку на закупку: {full_product_name} — {quantity} {unit}",
                    type="info",
                    request_id=request_obj.id
                )

        db.session.commit()
        return jsonify({
            "success": True,
            "message": f"Заявка отправлена! Создано заявок: {len(requests_data)}"
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при сохранении заявки: {e}")
        return jsonify({"error": "Ошибка при сохранении заявки"}), 500


@routes.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if current_user.role != "admin":
        return redirect("/")

    # === ОБНОВЛЁННАЯ СТАТИСТИКА ЗА ТЕКУЩУЮ НЕДЕЛЮ ===
    from datetime import datetime, timedelta

    # Определяем границы текущей учебной недели (пн-пт)
    today = datetime.today().date()
    monday = today - timedelta(days=today.weekday())  # Понедельник текущей недели
    friday = monday + timedelta(days=4)  # Пятница текущей недели

    # Обработка заявок + ПОПОЛНЕНИЕ ОСТАТКОВ
    if request.method == "POST":
        req_id = request.form.get("id")
        new_status = request.form.get("status")
        if req_id and new_status in ["approved", "rejected"]:
            req = db.session.get(PurchaseRequest, req_id)
            if req:
                req.status = new_status
                # === УВЕДОМЛЕНИЕ ПОВАРУ О РЕЗУЛЬТАТЕ ===
                status_text = "одобрена" if new_status == "approved" else "отклонена"
                status_type = "success" if new_status == "approved" else "warning"
                create_notification(
                    user_id=req.cook_id,
                    title=f"📦 Заявка {status_text}",
                    message=f"Ваша заявка на закупку «{req.product}» была {status_text} администратором.",
                    type=status_type,
                    request_id=req.id
                )
                # Пополнение склада (как в оригинальном коде)
                if new_status == "approved":
                    # Извлекаем название до скобки: "Молоко (л)" → "Молоко"
                    product_name = req.product.split(" (")[0]
                    ingredient = Ingredient.query.filter_by(name=product_name).first()
                    if ingredient:
                        product = Product.query.filter_by(ingredient_id=ingredient.id).first()
                        if product:
                            product.quantity += req.quantity
                        else:
                            # На случай, если продукт отсутствует
                            db.session.add(Product(
                                ingredient_id=ingredient.id,
                                quantity=req.quantity,
                                unit=req.unit or "г"
                            ))
                db.session.commit()
                return redirect("/admin")

    # === СБОР СТАТИСТИКИ ТОЛЬКО ЗА ТЕКУЩУЮ НЕДЕЛЮ ===
    # 1️⃣ Активные ученики (динамически обновляется)
    active_students = User.query.filter_by(role="student", is_active=True).all()
    total_students = len(active_students)
    max_possible = total_students * 10  # 5 дней × 2 приёма = 10

    # 2️⃣ Оплаченные заказы ЗА ТЕКУЩУЮ НЕДЕЛЮ (только будние дни)
    paid_orders_week = Order.query.filter(
        Order.status == "paid",
        Order.serving_date >= monday,
        Order.serving_date <= friday
    ).all()
    total_paid = len(paid_orders_week)

    # 3️⃣ Полученные заказы ЗА ТЕКУЩУЮ НЕДЕЛЮ
    collected_orders_week = Order.query.filter(
        Order.status == "paid",
        Order.student_confirmed == True,
        Order.serving_date >= monday,
        Order.serving_date <= friday
    ).all()
    total_consumed = len(collected_orders_week)

    # 4️⃣ Статистика по ученикам — только активные
    student_stats = []
    for student in active_students:
        # Считаем оплаченные и полученные ТОЛЬКО за текущую неделю
        paid_week = Order.query.filter(
            Order.student_id == student.id,
            Order.status == "paid",
            Order.serving_date >= monday,
            Order.serving_date <= friday
        ).count()

        consumed_week = Order.query.filter(
            Order.student_id == student.id,
            Order.status == "paid",
            Order.student_confirmed == True,
            Order.serving_date >= monday,
            Order.serving_date <= friday
        ).count()

        # Максимум за неделю: 10 приёмов
        attendance_pct = round((consumed_week / 10) * 100) if 10 > 0 else 0
        student_stats.append({
            "student": student,
            "paid": paid_week,
            "consumed": consumed_week,
            "attendance_pct": min(100, attendance_pct)
        })

    requests = PurchaseRequest.query.all()
    return render_template(
        "admin.html",
        total_paid=total_paid,
        total_consumed=total_consumed,
        total_students=total_students,
        max_possible=max_possible,  # Передаём явно для наглядности
        student_stats=student_stats,
        requests=requests,
        week_range=f"{monday.strftime('%d.%m')} - {friday.strftime('%d.%m')}"  # Опционально: отображать период недели
    )


@routes.route("/admin/menu", methods=["GET", "POST"])
@login_required
def admin_menu():
    if current_user.role != "admin":
        return redirect("/")

    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    day_names = {
        "monday": "Понедельник",
        "tuesday": "Вторник",
        "wednesday": "Среда",
        "thursday": "Четверг",
        "friday": "Пятница"
    }

    if request.method == "POST":
        # Получаем все ингредиенты для маппинга по имени
        all_ingredients = {ing.name: ing.id for ing in Ingredient.query.all()}

        for day in days:
            for meal_type in ["breakfast", "lunch"]:
                # Основные поля
                name = request.form.get(f"{day}_{meal_type}_name", "").strip()
                price_str = request.form.get(f"{day}_{meal_type}_price", "").strip()

                try:
                    price = float(price_str) if price_str else 0.0
                except ValueError:
                    price = 0.0

                # Найдём или создадим блюдо
                meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
                if not meal:
                    meal = Meal(day_of_week=day, meal_type=meal_type)
                    db.session.add(meal)

                meal.name = name
                meal.price = price

                # Удалим старые ингредиенты
                MealIngredient.query.filter_by(meal_id=meal.id).delete()

                # Добавим новые ингредиенты
                idx = 0
                while True:
                    ing_name = request.form.get(f"{day}_{meal_type}_ing_name_{idx}")
                    if ing_name is None:
                        break

                    ing_name = ing_name.strip()
                    if not ing_name:
                        idx += 1
                        continue

                    qty_str = request.form.get(f"{day}_{meal_type}_ing_qty_{idx}", "0")
                    unit = request.form.get(f"{day}_{meal_type}_ing_unit_{idx}", "г")

                    try:
                        qty = float(qty_str) if qty_str else 0.0
                    except ValueError:
                        qty = 0.0

                    if qty <= 0:
                        idx += 1
                        continue

                    # Убедимся, что ингредиент существует
                    if ing_name not in all_ingredients:
                        new_ing = Ingredient(name=ing_name)
                        db.session.add(new_ing)
                        db.session.flush()  # Получаем ID без коммита
                        all_ingredients[ing_name] = new_ing.id

                    db.session.add(MealIngredient(
                        meal_id=meal.id,
                        ingredient_id=all_ingredients[ing_name],
                        quantity=qty,
                        unit=unit
                    ))

                    idx += 1

        db.session.commit()

        # === УВЕДОМЛЕНИЕ ВСЕМ ПОЛЬЗОВАТЕЛЯМ ОБ ИЗМЕНЕНИИ МЕНЮ ===
        all_users = User.query.filter(User.role.in_(["student", "cook"])).all()
        user_ids = [user.id for user in all_users]

        create_bulk_notifications(
            user_ids,
            title="🍽️ Меню обновлено",
            message="Администратор обновил меню на неделю. Проверьте актуальное меню в своём кабинете.",
            type="info"
        )

        return redirect("/admin/menu")

    # Загрузка данных для GET-запроса
    meals_data = {}
    for day in days:
        meals_data[day] = {"breakfast": {}, "lunch": {}}
        for meal_type in ["breakfast", "lunch"]:
            meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
            if meal:
                ingredients = []
                for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
                    ing = db.session.get(Ingredient, mi.ingredient_id)
                    if ing:
                        ingredients.append({
                            "name": ing.name,
                            "quantity": mi.quantity,
                            "unit": mi.unit
                        })
                meals_data[day][meal_type] = {
                    "name": meal.name,
                    "price": meal.price,
                    "ingredients": ingredients
                }
            else:
                meals_data[day][meal_type] = {
                    "name": "",
                    "price": "",
                    "ingredients": []
                }

    return render_template(
        "admin_menu.html",
        days=days,
        day_names=day_names,
        meals=meals_data
    )


@routes.route("/admin/prices", methods=["GET", "POST"])
@login_required
def admin_prices():
    if current_user.role != "admin":
        return redirect("/")

    ingredients = Ingredient.query.order_by(Ingredient.name).all()

    if request.method == "POST":
        for ing in ingredients:
            price_str = request.form.get(f"price_{ing.id}", "0")
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                price = 0.0
            ing.price_per_unit = max(0.0, price)

        db.session.commit()

        # === УВЕДОМЛЕНИЕ ПОВАРАМ ОБ ИЗМЕНЕНИИ ЦЕН ===
        cook_users = User.query.filter_by(role="cook").all()
        cook_ids = [cook.id for cook in cook_users]

        create_bulk_notifications(
            cook_ids,
            title="💰 Цены на продукты обновлены",
            message="Администратор обновил цены на продукты. Проверьте актуальные цены при формировании заявок.",
            type="info"
        )

        flash("Цены успешно обновлены!", "success")
        return redirect("/admin/prices")

    return render_template("admin_prices.html", ingredients=ingredients)


@routes.route("/cook/write_off", methods=["POST"])
@login_required
def write_off():
    if current_user.role != "cook":
        return redirect("/cook")

    ing_id = request.form.get("ingredient_id", type=int)
    qty = request.form.get("quantity", type=float)
    reason = request.form.get("reason", "Порча")  # опционально

    if ing_id and qty and qty > 0:
        product = Product.query.filter_by(ingredient_id=ing_id).first()
        if product and product.quantity >= qty:
            # Списываем со склада
            product.quantity -= qty

            # Сохраняем в журнал
            ingredient = db.session.get(Ingredient, ing_id)
            db.session.add(WriteOff(
                ingredient_id=ing_id,
                quantity=qty,
                unit=product.unit if product else "г",
                reason=reason,
                cook_id=current_user.id
            ))

            db.session.commit()

            # === УВЕДОМЛЕНИЕ АДМИНИСТРАТОРАМ О СПИСАНИИ ===
            admin_users = User.query.filter_by(role="admin").all()
            admin_ids = [admin.id for admin in admin_users]

            cost = qty * ingredient.price_per_unit

            create_bulk_notifications(
                admin_ids,
                title="🗑️ Продукт списан",
                message=f"Повар {current_user.full_name} списал {qty} {product.unit} продукта «{ingredient.name}». Причина: {reason}. Стоимость: {cost:.2f} ₽",
                type="warning"
            )

            flash(f"Списано {qty} {product.unit} продукта «{ingredient.name}».", "success")
        else:
            flash("Недостаточно остатков для списания.", "error")
    else:
        flash("Неверные данные для списания.", "error")

    return redirect("/cook")


@routes.route("/cook/request_purchase", methods=["POST"])
@login_required
def request_purchase():
    if current_user.role != "cook":
        return redirect("/cook")

    product_name = request.form.get("product", "").strip()
    quantity_str = request.form.get("quantity", "0").strip()
    unit = request.form.get("unit", "г").strip()

    # Валидация
    try:
        quantity = float(quantity_str)
    except (ValueError, TypeError):
        flash("Неверный формат количества.", "error")
        return redirect("/cook")

    if quantity <= 0 or not product_name:
        flash("Количество должно быть больше нуля и указан продукт.", "error")
        return redirect("/cook")

    # Создаём заявку
    db.session.add(PurchaseRequest(
        product=product_name,
        quantity=quantity,
        unit=unit,
        cook_id=current_user.id,
        status="pending"  # ← обязательно указываем статус
    ))
    db.session.commit()

    # === УВЕДОМЛЕНИЕ АДМИНИСТРАТОРАМ ===
    admin_users = User.query.filter_by(role="admin").all()
    admin_ids = [admin.id for admin in admin_users]

    create_bulk_notifications(
        admin_ids,
        title="📦 Новая заявка на закупку",
        message=f"Повар {current_user.full_name} отправил заявку на закупку: {product_name} — {quantity} {unit}",
        type="info"
    )

    flash("Заявка на закупку отправлена!", "success")
    return redirect("/cook")


@routes.route("/admin/reports", methods=["GET", "POST"])
@login_required
def admin_reports():
    if current_user.role != "admin":
        return redirect("/")

    from datetime import datetime, timedelta
    from collections import defaultdict

    # === Определение периода отчёта ===
    today = datetime.today().date()
    default_start = today - timedelta(days=today.weekday())  # понедельник текущей недели
    default_end = default_start + timedelta(days=4)  # пятница

    # Получаем даты из формы или URL
    start_str = request.args.get("start_date") or request.form.get("start_date")
    end_str = request.args.get("end_date") or request.form.get("end_date")

    try:
        if start_str and end_str:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            if start_date > end_date:
                raise ValueError("Начало позже конца")
        else:
            start_date = default_start
            end_date = default_end
    except:
        # При ошибке — используем текущую неделю
        start_date = default_start
        end_date = default_end

    # === Финансовый отчёт ===
    revenue_by_day = {}
    total_revenue = 0.0

    paid_orders = Order.query.filter(
        Order.status == "paid",
        Order.paid_at.isnot(None),
        Order.serving_date >= start_date,
        Order.serving_date <= end_date
    ).all()

    # Группируем по дням (только будни)
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    day_names_map = {
        "monday": "Пн", "tuesday": "Вт", "wednesday": "Ср",
        "thursday": "Чт", "friday": "Пт"
    }

    # Инициализируем все дни в периоде
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # только пн-пт
            day_key = weekdays[current.weekday()]
            revenue_by_day[day_key] = {"breakfast": 0.0, "lunch": 0.0, "total": 0.0}
        current += timedelta(days=1)

    for order in paid_orders:
        if order.serving_date.weekday() >= 5:
            continue  # пропускаем выходные

        day_key = weekdays[order.serving_date.weekday()]
        meal = Meal.query.filter_by(day_of_week=day_key, meal_type=order.meal_type).first()
        price = meal.price if meal else 0.0

        if day_key in revenue_by_day:
            revenue_by_day[day_key][order.meal_type] += price
            revenue_by_day[day_key]["total"] += price
            total_revenue += price

    # === Посещаемость ===
    attendance_by_day = {k: {"breakfast": 0, "lunch": 0, "total": 0} for k in revenue_by_day.keys()}

    collected_orders = [o for o in paid_orders if o.is_collected and o.student_confirmed]
    for order in collected_orders:
        if order.serving_date.weekday() >= 5:
            continue

        day_key = weekdays[order.serving_date.weekday()]
        if day_key in attendance_by_day:
            attendance_by_day[day_key][order.meal_type] += 1
            attendance_by_day[day_key]["total"] += 1

    # === ПЛАН vs ФАКТ (на основе заказов в периоде) ===
    ingredient_prices = {ing.id: ing.price_per_unit for ing in Ingredient.query.all()}

    # План = сумма всех оплаченных заказов в периоде
    plan_usage = defaultdict(lambda: {"quantity": 0.0, "unit": "г", "cost": 0.0})
    for order in paid_orders:
        try:
            ingredients = json.loads(order.meal_ingredients)
            for ing in ingredients:
                name = ing["name"]
                qty = float(ing["qty"])
                unit = ing["unit"]
                ingredient_obj = Ingredient.query.filter_by(name=name).first()
                price_per = ingredient_obj.price_per_unit if ingredient_obj else 0.0
                cost = qty * price_per
                plan_usage[name]["quantity"] += qty
                plan_usage[name]["unit"] = unit
                plan_usage[name]["cost"] += cost
        except:
            continue

    # Факт = сумма выданных заказов в периоде
    usage = defaultdict(lambda: {"quantity": 0.0, "unit": "г", "cost": 0.0})
    for order in collected_orders:
        try:
            ingredients = json.loads(order.meal_ingredients)
            for ing in ingredients:
                name = ing["name"]
                qty = float(ing["qty"])
                unit = ing["unit"]
                ingredient_obj = Ingredient.query.filter_by(name=name).first()
                price_per = ingredient_obj.price_per_unit if ingredient_obj else 0.0
                cost = qty * price_per
                usage[name]["quantity"] += qty
                usage[name]["unit"] = unit
                usage[name]["cost"] += cost
        except:
            continue

    # Объединяем план и факт
    plan_vs_fact = []
    all_names = set(plan_usage.keys()) | set(usage.keys())
    for name in sorted(all_names):
        plan = plan_usage.get(name, {"quantity": 0.0, "unit": "г", "cost": 0.0})
        fact = usage.get(name, {"quantity": 0.0, "unit": "г", "cost": 0.0})
        unit = plan["unit"] if plan["quantity"] > 0 else fact["unit"]
        deviation_qty = fact["quantity"] - plan["quantity"]
        deviation_cost = fact["cost"] - plan["cost"]
        plan_vs_fact.append({
            "name": name,
            "plan_qty": plan["quantity"],
            "fact_qty": fact["quantity"],
            "deviation_qty": deviation_qty,
            "unit": unit,
            "plan_cost": plan["cost"],
            "fact_cost": fact["cost"],
            "deviation_cost": deviation_cost
        })

    plan_vs_fact.sort(key=lambda x: abs(x["deviation_cost"]), reverse=True)
    total_usage_cost = sum(item["fact_cost"] for item in plan_vs_fact)

    # === РУЧНЫЕ СПИСАНИЯ В ПЕРИОДЕ ===
    write_offs = WriteOff.query.filter(
        WriteOff.created_at >= start_date,
        WriteOff.created_at < end_date + timedelta(days=1)
    ).order_by(WriteOff.created_at.desc()).all()

    manual_write_offs_list = []
    total_manual_cost = 0.0
    for w in write_offs:
        ingredient = db.session.get(Ingredient, w.ingredient_id)
        if not ingredient:
            continue

        cost = w.quantity * ingredient.price_per_unit
        total_manual_cost += cost

        cook = db.session.get(User, w.cook_id)
        manual_write_offs_list.append({
            "product": ingredient.name,
            "quantity": w.quantity,
            "unit": w.unit,
            "reason": w.reason,
            "date": w.created_at.strftime('%d.%m %H:%M'),
            "cook_name": cook.full_name if cook else "—",
            "cost": cost
        })

    # === ЗАТРАТЫ НА ЗАКУПКИ В ПЕРИОДЕ ===
    approved_purchases = PurchaseRequest.query.filter(
        PurchaseRequest.status == "approved",
        PurchaseRequest.timestamp >= start_date,
        PurchaseRequest.timestamp < end_date + timedelta(days=1)
    ).all()

    total_spent = 0.0
    for req in approved_purchases:
        product_name = req.product.split(" (")[0]
        ingredient = Ingredient.query.filter_by(name=product_name).first()
        if ingredient:
            total_spent += req.quantity * ingredient.price_per_unit

    # === ДЕФИЦИТ (расчёт на всех учеников, но не зависит от периода) ===
    total_students = User.query.filter_by(role="student").count() or 1

    ingredient_needs = db.session.query(
        Ingredient.id,
        Ingredient.name,
        MealIngredient.unit,
        db.func.sum(MealIngredient.quantity * total_students).label('needed')
    ).join(MealIngredient, Ingredient.id == MealIngredient.ingredient_id) \
        .group_by(Ingredient.id, Ingredient.name, MealIngredient.unit) \
        .all()

    stock_map = {p.ingredient_id: p for p in Product.query.all()}

    deficit_details = []
    total_cost_deficit = 0.0
    for ing_id, name, unit, needed in ingredient_needs:
        current = stock_map.get(ing_id).quantity if stock_map.get(ing_id) else 0.0
        deficit = max(0.0, float(needed) - float(current))
        if deficit > 0:
            price_per = ingredient_prices.get(ing_id, 0.0)
            cost = deficit * price_per
            total_cost_deficit += cost
            deficit_details.append({
                "name": name,
                "unit": unit,
                "needed": float(needed),
                "current": float(current),
                "deficit": deficit,
                "cost": cost
            })

    deficit_details.sort(key=lambda x: x["cost"], reverse=True)

    # === Подготовка данных для графиков ===
    chart_days_keys = list(revenue_by_day.keys())  # ["monday", "tuesday", ...]
    chart_days = [day_names_map[day] for day in chart_days_keys]  # ["Пн", "Вт", ...]
    chart_revenue = [revenue_by_day[day]["total"] for day in chart_days_keys]
    chart_breakfasts = [attendance_by_day[day]["breakfast"] for day in chart_days_keys]
    chart_lunches = [attendance_by_day[day]["lunch"] for day in chart_days_keys]

    top_10_plan_vs_fact = plan_vs_fact[:10]

    return render_template(
        "admin_reports.html",
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        days=list(revenue_by_day.keys()),
        day_names=day_names_map,
        revenue_by_day=revenue_by_day,
        attendance_by_day=attendance_by_day,
        total_revenue=total_revenue,
        total_cost_deficit=total_cost_deficit,
        total_spent=total_spent,
        deficit_details=deficit_details,
        usage_list=plan_vs_fact,  # для совместимости
        total_usage_cost=total_usage_cost,
        plan_vs_fact=plan_vs_fact,
        manual_write_offs=manual_write_offs_list,
        total_manual_cost=total_manual_cost,
        # НОВЫЕ ПЕРЕМЕННЫЕ ДЛЯ ГРАФИКОВ:
        chart_days=chart_days,
        chart_revenue=chart_revenue,
        chart_breakfasts=chart_breakfasts,
        chart_lunches=chart_lunches,
        top_10_plan_vs_fact=top_10_plan_vs_fact
    )


@routes.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        flash('⚠️ Файл не выбран', 'warning')
        return redirect('/student')

    file = request.files['avatar']

    if file.filename == '':
        flash('⚠️ Файл не выбран', 'warning')
        return redirect('/student')

    if file and allowed_file(file.filename):
        # Удаляем старую аватарку (если не стандартная)
        if current_user.avatar_filename != 'default_avatar.png':
            old_path = os.path.join(current_app.config['AVATARS_FOLDER'], current_user.avatar_filename)
            if os.path.exists(old_path):
                os.remove(old_path)

        # Сохраняем новую с уникальным именем
        filename = secure_filename(f"{current_user.id}_{file.filename}")
        filepath = os.path.join(current_app.config['AVATARS_FOLDER'], filename)
        file.save(filepath)

        # Обновляем в базе
        current_user.avatar_filename = filename
        db.session.commit()

        flash('✅ Аватарка успешно обновлена!', 'success')
        return redirect('/student')

    flash('❌ Недопустимый формат файла. Разрешены: png, jpg, jpeg, gif', 'error')
    return redirect('/student')


# === УПРАВЛЕНИЕ УЧЕНИКАМИ ===
@routes.route("/admin/students")
@login_required
def admin_students():
    """Список всех учеников для администратора"""
    if current_user.role != "admin":
        return redirect("/")

    # Показываем только активных учеников
    students = User.query.filter_by(role="student", is_active=True).order_by(User.full_name).all()

    # Получаем аллергии и информацию о гибком абонементе для каждого ученика
    students_with_data = []
    for student in students:
        allergy = Allergy.query.filter_by(student_id=student.id).first()

        # Получаем активный гибкий абонемент
        active_flexible = FlexibleSubscription.query.filter_by(
            student_id=student.id,
            is_active=True
        ).first()

        students_with_data.append({
            'student': student,
            'allergy': allergy.text if allergy else "—",
            'flexible_sub': active_flexible  # Добавляем информацию о гибком абонементе
        })

    # Считаем архивированных учеников
    archived_count = User.query.filter_by(role="student", is_active=False).count()

    return render_template("admin_students.html", students=students_with_data, archived_count=archived_count)


@routes.route("/admin/student/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_student(student_id):
    """Редактирование профиля ученика"""
    if current_user.role != "admin":
        return redirect("/")

    student = db.session.get(User, student_id)
    if not student:
        abort(404)

    if student.role != "student":
        flash("Пользователь не является учеником", "error")
        return redirect("/admin/students")

    if request.method == "POST":
        # Получаем данные из формы
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        class_name = request.form.get("class_name", "").strip()
        balance = request.form.get("balance", "0")
        has_subscription = request.form.get("has_subscription") == "on"

        # Валидация
        if not full_name or not email:
            flash("ФИО и email обязательны", "error")
            return redirect(request.url)

        # Проверка уникальности email
        existing_user = User.query.filter_by(email=email).first()
        if existing_user and existing_user.id != student_id:
            flash("Пользователь с таким email уже существует", "error")
            return redirect(request.url)

        try:
            # Обновляем данные
            student.full_name = full_name
            student.email = email
            student.class_name = class_name

            # Баланс
            student.balance = float(balance) if balance else 0.0

            # Абонемент
            student.has_subscription = has_subscription

            db.session.commit()

            # Уведомление ученику
            create_notification(
                user_id=student.id,
                title="✏️ Профиль обновлён",
                message="Администратор обновил данные вашего профиля.",
                type="info"
            )

            flash(f"Профиль ученика {full_name} успешно обновлён!", "success")
            return redirect("/admin/students")

        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка при сохранении: {str(e)}", "error")
            return redirect(request.url)

    # GET запрос - показываем форму
    return render_template("admin_edit_student.html", student=student)


@routes.route("/admin/student/<int:student_id>/delete", methods=["POST"])
@login_required
def admin_delete_student(student_id):
    """Архивирование ученика (мягкое удаление)"""
    if current_user.role != "admin":
        return redirect("/")

    student = db.session.get(User, student_id)
    if not student:
        abort(404)

    if student.role != "student":
        flash("Пользователь не является учеником", "error")
        return redirect("/admin/students")

    if not student.is_active:
        flash("Ученик уже удалён", "warning")
        return redirect("/admin/students")

    student_name = student.full_name
    refund_amount = student.balance

    try:
        # 1. Возврат денег на отдельный счёт (если баланс > 0)
        if refund_amount > 0:
            # Создаём запись о возврате средств
            refund_log = DeletionLog(
                user_id=student.id,
                user_email=student.email,
                user_full_name=student.full_name,
                deleted_by_admin_id=current_user.id,
                deleted_by_admin_email=current_user.email,
                refund_amount=refund_amount,
                reason="Архивирование ученика с возвратом средств"
            )
            db.session.add(refund_log)

            # Можно также создать транзакцию в отдельной таблице, если она есть
            # Например: Transaction(student_id=student.id, amount=refund_amount, type="refund", ...)

        # 2. Архивируем ученика вместо полного удаления
        student.is_active = False
        student.deleted_at = datetime.utcnow()
        student.deleted_by = current_user.id

        # 3. Записываем в лог удаление
        deletion_log = DeletionLog(
            user_id=student.id,
            user_email=student.email,
            user_full_name=student.full_name,
            deleted_by_admin_id=current_user.id,
            deleted_by_admin_email=current_user.email,
            refund_amount=refund_amount,
            reason=request.form.get("reason", "Ученик удалён администратором")
        )
        db.session.add(deletion_log)

        # 4. Удаляем связанные данные (опционально - можно оставить для истории)
        # Allergy.query.filter_by(student_id=student_id).delete()
        # Order.query.filter_by(student_id=student_id).delete()
        # Review.query.filter_by(student_id=student_id).delete()

        db.session.commit()

        # Формируем сообщение о возврате
        if refund_amount > 0:
            flash(f"✅ Ученик {student_name} архивирован. Возвращено {refund_amount:.2f} ₽ на счёт возвратов.",
                  "success")
        else:
            flash(f"✅ Ученик {student_name} успешно архивирован.", "success")

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка при архивировании: {e}")
        flash(f"❌ Ошибка при архивировании: {str(e)}", "error")

    return redirect("/admin/students")


@routes.route("/admin/students/archived")
@login_required
def admin_archived_students():
    """Список архивированных учеников"""
    if current_user.role != "admin":
        return redirect("/")

    # Показываем только неактивных (архивированных) учеников
    students = User.query.filter_by(role="student", is_active=False).order_by(User.deleted_at.desc()).all()

    # Получаем логи удалений
    students_with_data = []
    for student in students:
        deletion_log = DeletionLog.query.filter_by(user_id=student.id).order_by(DeletionLog.deleted_at.desc()).first()
        students_with_data.append({
            'student': student,
            'deleted_by': deletion_log.deleted_by_admin_email if deletion_log else "—",
            'deleted_at': deletion_log.deleted_at if deletion_log else student.deleted_at,
            'refund_amount': deletion_log.refund_amount if deletion_log else 0
        })

    return render_template("admin_archived_students.html", students=students_with_data)


@routes.route("/admin/student/add", methods=["GET", "POST"])
@login_required
def admin_add_student():
    """Добавление нового ученика администратором"""
    if current_user.role != "admin":
        abort(403)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        class_name = request.form.get("class_name", "").strip()
        initial_balance = request.form.get("initial_balance", "0")
        has_subscription = request.form.get("has_subscription") == "on"

        if not full_name or not email or not class_name:
            flash("ФИО, email и класс обязательны", "error")
            return redirect(request.url)

        if User.query.filter_by(email=email).first():
            flash(f"Пользователь с email {email} уже существует", "error")
            return redirect(request.url)

        try:
            # Генерируем надежный пароль (12 символов)
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            password = ''.join(secrets.choice(alphabet) for _ in range(12))

            user = User(
                full_name=full_name,
                email=email,
                password=generate_password_hash(password),
                role="student",
                class_name=class_name,
                balance=float(initial_balance) if initial_balance else 0.0,
                has_subscription=has_subscription,
                is_active=True
            )
            db.session.add(user)
            db.session.commit()

            create_notification(
                user_id=current_user.id,
                title="✅ Ученик добавлен",
                message=f"Ученик {full_name} успешно добавлен в систему. Временный пароль: {password}",
                type="success"
            )
            flash(f"✅ Ученик {full_name} успешно добавлен! Временный пароль: {password}", "success")
            return redirect("/admin/students")
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка при добавлении ученика: {e}")
            flash(f"❌ Ошибка: {str(e)}", "error")
            return redirect(request.url)
    return render_template("admin_add_student.html")


@routes.route('/student/subscription/flexible')
@login_required
def flexible_subscription():
    """Страница гибкого абонемента"""
    if current_user.role != 'student':
        flash('Доступ запрещён', 'error')
        return redirect('/student')

    # Проверяем, есть ли уже активный гибкий абонемент
    active_sub = FlexibleSubscription.query.filter_by(
        student_id=current_user.id,  # ← ИСПРАВЛЕНО: было current_user.student.id
        is_active=True
    ).filter(FlexibleSubscription.expires_at > datetime.utcnow()).first()

    return render_template('flexible_subscription.html', active_sub=active_sub)


@routes.route('/api/flexible-subscription/calculate', methods=['POST'])
@login_required
def calculate_flexible_price():
    """Расчёт стоимости гибкого абонемента с деталями по дням и учётом только будних дней"""
    if current_user.role != 'student':
        return jsonify({'error': 'Доступ запрещён'}), 403

    try:
        data = request.get_json()
        days_count = int(data.get('days_count', 10))
        days_config = data.get('days_config', {})

        # === ЗАГРУЗКА РЕАЛЬНЫХ ЦЕН ИЗ БАЗЫ ДАННЫХ ===
        meal_details = {}
        selected_meals = {}
        weekly_price = 0.0
        meal_count = 0

        # Карта дней недели для сравнения
        day_order = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4}

        for day_key in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            # Инициализируем данные дня
            meal_details[day_key] = {
                'breakfast': None,
                'lunch': None
            }
            selected_meals[day_key] = {
                'breakfast': False,
                'lunch': False,
                'breakfast_price': 0.0,
                'lunch_price': 0.0
            }

            # === ЗАВТРАК ===
            breakfast = Meal.query.filter_by(day_of_week=day_key, meal_type='breakfast').first()
            if breakfast:
                # Загружаем ингредиенты
                ingredients = []
                for mi in MealIngredient.query.filter_by(meal_id=breakfast.id).all():
                    ing = db.session.get(Ingredient, mi.ingredient_id)
                    if ing:
                        ingredients.append({
                            'name': ing.name,
                            'quantity': float(mi.quantity),
                            'unit': mi.unit
                        })

                meal_details[day_key]['breakfast'] = {
                    'name': breakfast.name,
                    'price': float(breakfast.price),
                    'ingredients': ingredients
                }

            # === ОБЕД ===
            lunch = Meal.query.filter_by(day_of_week=day_key, meal_type='lunch').first()
            if lunch:
                # Загружаем ингредиенты
                ingredients = []
                for mi in MealIngredient.query.filter_by(meal_id=lunch.id).all():
                    ing = db.session.get(Ingredient, mi.ingredient_id)
                    if ing:
                        ingredients.append({
                            'name': ing.name,
                            'quantity': float(mi.quantity),
                            'unit': mi.unit
                        })

                meal_details[day_key]['lunch'] = {
                    'name': lunch.name,
                    'price': float(lunch.price),
                    'ingredients': ingredients
                }

            # === РАСЧЁТ ВЫБРАННЫХ ПРИЁМОВ ===
            day_settings = days_config.get(day_key, {})
            breakfast_selected = day_settings.get('breakfast', False)
            lunch_selected = day_settings.get('lunch', False)

            if breakfast_selected and meal_details[day_key]['breakfast']:
                price = meal_details[day_key]['breakfast']['price']
                weekly_price += price
                meal_count += 1
                selected_meals[day_key]['breakfast'] = True
                selected_meals[day_key]['breakfast_price'] = price

            if lunch_selected and meal_details[day_key]['lunch']:
                price = meal_details[day_key]['lunch']['price']
                weekly_price += price
                meal_count += 1
                selected_meals[day_key]['lunch'] = True
                selected_meals[day_key]['lunch_price'] = price

        # === РАСЧЁТ ИТОГОВОЙ СТОИМОСТИ ===
        # ВАЖНО: 1 неделя = 5 будних дней (пн-пт)
        weeks_count = days_count / 5
        total_price = weekly_price * weeks_count

        # === ОПРЕДЕЛЕНИЕ СДВИГА НА СЛЕДУЮЩУЮ НЕДЕЛЮ ===
        today = datetime.now().date()
        current_weekday = today.weekday()  # 0=пн, 4=пт

        # Проверяем, есть ли среди выбранных дней хотя бы один не прошедший сегодня
        has_future_days = False
        for day_key, selected in selected_meals.items():
            if selected['breakfast'] or selected['lunch']:
                if day_order[day_key] >= current_weekday:
                    has_future_days = True
                    break

        # Если все выбранные дни уже прошли в текущей неделе — сдвигаем на следующую неделю
        needs_shift = not has_future_days and current_weekday < 4  # Не в пятницу

        return jsonify({
            'success': True,
            'total_price': round(total_price, 2),
            'meal_count': meal_count,
            'weeks_count': weeks_count,
            'meal_details': meal_details,  # Полные данные о блюдах
            'selected_meals': selected_meals,  # Выбранные приёмы с ценами
            'needs_shift': needs_shift,  # Флаг сдвига
            'shift_days': 7 if needs_shift else 0
        })
    except Exception as e:
        import traceback
        print("Ошибка в calculate_flexible_price:", traceback.format_exc())
        return jsonify({'error': f'Ошибка расчёта: {str(e)}'}), 500


@routes.route('/student/subscription/flexible/purchase', methods=['POST'])
@login_required
def purchase_flexible_subscription():
    """Покупка гибкого абонемента с проверкой на уже оплаченные приёмы"""
    if current_user.role != 'student':
        flash('Доступ запрещён', 'error')
        return redirect('/student')
    try:
        days_count = int(request.form.get('days_count'))
        days_config_json = request.form.get('days_config')
        needs_shift = request.form.get('needs_shift') == 'true'

        if not days_config_json:
            flash('Ошибка: конфигурация не передана', 'error')
            return redirect('/student/subscription/flexible')

        days_config = json.loads(days_config_json)

        # === ОПРЕДЕЛЯЕМ ДАТУ НАЧАЛА АБОНЕМЕНТА ===
        start_date = datetime.now().date()
        if needs_shift:
            days_until_monday = 7 - start_date.weekday()
            start_date += timedelta(days=days_until_monday)
            flash(f'ℹ️ Абонемент начнётся с понедельника ({start_date.strftime("%d.%m")})', 'info')

        # === ПРОВЕРКА НА СУЩЕСТВУЮЩИЙ АКТИВНЫЙ АБОНЕМЕНТ ===
        existing_sub = FlexibleSubscription.query.filter_by(
            student_id=current_user.id,
            is_active=True
        ).first()
        if existing_sub:
            flash('У вас уже есть активный гибкий абонемент. Дождитесь его окончания.', 'error')
            return redirect('/student/subscription/flexible')

        # === КАРТА ДНЕЙ НЕДЕЛИ ===
        day_map = {
            0: 'monday',
            1: 'tuesday',
            2: 'wednesday',
            3: 'thursday',
            4: 'friday'
        }

        # === ПЕРЕСЧЁТ СТОИМОСТИ И ФОРМИРОВАНИЕ ЗАКАЗОВ БЕЗ ДУБЛИРОВАНИЯ ===
        recalculated_total = 0.0
        meals_to_create = []
        skipped_meals = []  # Для информирования пользователя

        current_date = start_date
        actual_days_processed = 0

        while actual_days_processed < days_count:
            if current_date.weekday() < 5:  # Только будние дни
                day_key = day_map[current_date.weekday()]
                day_config = days_config.get(day_key, {})

                # Проверка завтрака
                if day_config.get('breakfast'):
                    # Проверяем, не оплачен ли уже этот приём
                    existing = Order.query.filter_by(
                        student_id=current_user.id,
                        serving_date=current_date,
                        meal_type='breakfast',
                        status='paid'
                    ).first()

                    if existing:
                        skipped_meals.append((current_date, '🕗 завтрак'))
                    else:
                        meal = Meal.query.filter_by(day_of_week=day_key, meal_type='breakfast').first()
                        if meal:
                            # Собираем ингредиенты
                            ingredients_list = []
                            for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
                                ing = db.session.get(Ingredient, mi.ingredient_id)
                                if ing:
                                    ingredients_list.append({
                                        "name": ing.name,
                                        "qty": mi.quantity,
                                        "unit": mi.unit
                                    })
                            meals_to_create.append({
                                'day_key': day_key,
                                'meal_type': 'breakfast',
                                'serving_date': current_date,
                                'meal': meal,
                                'ingredients': ingredients_list
                            })
                            recalculated_total += meal.price

                # Проверка обеда
                if day_config.get('lunch'):
                    existing = Order.query.filter_by(
                        student_id=current_user.id,
                        serving_date=current_date,
                        meal_type='lunch',
                        status='paid'
                    ).first()

                    if existing:
                        skipped_meals.append((current_date, '🕐 обед'))
                    else:
                        meal = Meal.query.filter_by(day_of_week=day_key, meal_type='lunch').first()
                        if meal:
                            ingredients_list = []
                            for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
                                ing = db.session.get(Ingredient, mi.ingredient_id)
                                if ing:
                                    ingredients_list.append({
                                        "name": ing.name,
                                        "qty": mi.quantity,
                                        "unit": mi.unit
                                    })
                            meals_to_create.append({
                                'day_key': day_key,
                                'meal_type': 'lunch',
                                'serving_date': current_date,
                                'meal': meal,
                                'ingredients': ingredients_list
                            })
                            recalculated_total += meal.price

                actual_days_processed += 1
            current_date += timedelta(days=1)

        # === ИНФОРМИРОВАНИЕ О ПРОПУЩЕННЫХ УЖЕ ОПЛАЧЕННЫХ ПРИЁМАХ ===
        if skipped_meals:
            skipped_str = ", ".join([
                f"{date.strftime('%d.%m')} {mt}"
                for date, mt in skipped_meals
            ])
            flash(f'ℹ️ Пропущены уже оплаченные приёмы: {skipped_str}', 'info')

        # === ПРОВЕРКА: ЕСТЬ ЛИ ЧТО СОЗДАВАТЬ ===
        if not meals_to_create:
            flash('ℹ️ Все выбранные приёмы уже оплачены. Абонемент не создан.', 'info')
            return redirect('/student/subscription/flexible')

        # === ПРОВЕРКА БАЛАНСА ПО ПЕРЕСЧИТАННОЙ СУММЕ ===
        if current_user.balance < recalculated_total:
            flash(f'Недостаточно средств! Требуется {recalculated_total:.2f} ₽, доступно: {current_user.balance:.2f} ₽',
                  'error')
            return redirect('/student/subscription/flexible')

        # === СОЗДАНИЕ ЗАПИСИ ОБ АБОНЕМЕНТЕ ===
        last_serving_date = current_date - timedelta(days=1)
        new_sub = FlexibleSubscription(
            student_id=current_user.id,
            days_count=days_count,
            days_config=days_config,
            total_price=recalculated_total,  # Используем пересчитанную сумму!
            total_meals=len(meals_to_create),  # Только новые заказы
            start_date=datetime.combine(start_date, datetime.min.time()),
            expires_at=datetime.combine(last_serving_date, datetime.min.time()),
            is_active=True
        )
        db.session.add(new_sub)
        db.session.flush()  # ← Получаем ID без коммита

        # === СОЗДАНИЕ ЗАКАЗОВ ТОЛЬКО ДЛЯ НЕОПЛАЧЕННЫХ ПРИЁМОВ ===
        orders_created = []
        for item in meals_to_create:
            order = Order(
                student_id=current_user.id,
                day_of_week=item['day_key'],
                meal_type=item['meal_type'],
                serving_date=item['serving_date'],
                status='paid',
                paid_at=datetime.utcnow(),
                meal_name=item['meal'].name,
                meal_price=item['meal'].price,
                meal_ingredients=json.dumps(item['ingredients'], ensure_ascii=False),
                payment_source='flexible'  # ← СОЗДАН ГИБКИМ АБОНЕМЕНТОМ
            )
            db.session.add(order)
            orders_created.append(order)

        # === СПИСАНИЕ С БАЛАНСА ПЕРЕСЧИТАННОЙ СУММЫ ===
        current_user.balance -= recalculated_total
        db.session.commit()

        # === УВЕДОМЛЕНИЕ ===
        create_notification(
            user_id=current_user.id,
            title="✅ Гибкий абонемент оплачен",
            message=f"Гибкий абонемент успешно оплачен! Создано заказов: {len(orders_created)}. Стоимость: {recalculated_total:.2f} ₽",
            type="success"
        )
        flash(
            f'✅ Гибкий абонемент успешно оплачен! Создано заказов: {len(orders_created)}. Стоимость: {recalculated_total:.2f} ₽',
            'success')
        return redirect('/student/subscription/flexible')

    except Exception as e:
        db.session.rollback()
        import traceback
        print("Ошибка при оформлении абонемента:", traceback.format_exc())
        flash(f'Ошибка при оформлении абонемента: {str(e)}', 'error')
        return redirect('/student/subscription/flexible')


@routes.route('/api/flexible-subscription/status')
@login_required
def flexible_subscription_status():
    """Получение статуса гибкого абонемента"""
    if current_user.role != 'student':
        return jsonify({'error': 'Доступ запрещён'}), 403

    active_sub = FlexibleSubscription.query.filter_by(
        student_id=current_user.id,  # ← ИСПРАВЛЕНО
        is_active=True
    ).filter(FlexibleSubscription.expires_at > datetime.utcnow()).first()

    if active_sub:
        return jsonify({
            'has_active': True,
            'days_count': active_sub.days_count,
            'expires_at': active_sub.expires_at.strftime('%d.%m.%Y'),
            'total_meals': active_sub.total_meals,
            'total_price': active_sub.total_price
        })
    else:
        return jsonify({'has_active': False})


# === УПРАВЛЕНИЕ ОПЛАТАМИ АДМИНИСТРАТОРОМ ===
@routes.route("/admin/payments")
@login_required
def admin_payments():
    """Страница управления оплатами для администратора"""
    if current_user.role != "admin":
        return redirect("/")

    # Гибкие абонементы
    flexible_subs = FlexibleSubscription.query.order_by(FlexibleSubscription.created_at.desc()).all()

    # РАЗОВЫЕ ОПЛАТЫ - оплаченные И отменённые (только разовые)
    orders = Order.query.filter(
        Order.payment_source == 'single',  # Только разовые
        Order.status.in_(['paid', 'cancelled'])  # Оплаченные И отменённые
    ).order_by(Order.paid_at.desc()).all()

    # Все ученики
    students = User.query.filter_by(role="student", is_active=True).order_by(User.full_name).all()

    # Статистика
    total_flexible = len(flexible_subs)
    total_orders = len(orders)
    total_students = len(students)

    return render_template(
        "admin_payments.html",
        flexible_subs=flexible_subs,
        orders=orders,
        students=students,
        total_flexible=total_flexible,
        total_orders=total_orders,
        total_students=total_students,
        day_names=DAY_NAMES_RU
    )


@routes.route("/admin/payment/flexible/<int:sub_id>/cancel", methods=["POST"])
@login_required
def admin_cancel_flexible_subscription(sub_id):
    """Отмена гибкого абонемента с возвратом средств и отменой всех связанных заказов"""
    if current_user.role != "admin":
        flash("Доступ запрещён", "error")
        return redirect("/admin")

    subscription = db.session.get(FlexibleSubscription, sub_id)
    if not subscription:
        flash("Абонемент не найден", "error")
        return redirect("/admin/payments")

    if not subscription.is_active:
        flash("Абонемент уже отменён", "warning")
        return redirect("/admin/payments")

    student = db.session.get(User, subscription.student_id)
    if not student:
        flash("Ученик не найден", "error")
        return redirect("/admin/payments")

    # === НАХОДИМ И ОТМЕНЯЕМ ВСЕ ЗАКАЗЫ В ПЕРИОДЕ ДЕЙСТВИЯ АБОНЕМЕНТА ===
    orders_to_cancel = Order.query.filter(
        Order.student_id == subscription.student_id,
        Order.serving_date >= subscription.start_date.date(),
        Order.serving_date <= subscription.expires_at.date(),
        Order.status == 'paid'  # Только оплаченные
    ).all()

    orders_cancelled_count = 0
    for order in orders_to_cancel:
        order.status = 'cancelled'
        order.is_collected = False  # На случай, если уже выдан
        orders_cancelled_count += 1

    # Возврат средств на баланс
    refund_amount = subscription.total_price
    student.balance += refund_amount

    # Деактивация абонемента
    subscription.is_active = False

    db.session.commit()

    # Уведомление ученику
    create_notification(
        user_id=student.id,
        title="💰 Возврат средств",
        message=f"Администратор отменил ваш гибкий абонемент. Отменено заказов: {orders_cancelled_count}. Возвращено {refund_amount:.2f} ₽ на ваш баланс.",
        type="info"
    )

    flash(
        f"✅ Гибкий абонемент ученика {student.full_name} отменён. Отменено {orders_cancelled_count} заказов. Возвращено {refund_amount:.2f} ₽",
        "success")
    return redirect("/admin/payments")


@routes.route("/admin/payment/order/<int:order_id>/cancel", methods=["POST"])
@login_required
def admin_cancel_order(order_id):
    """Отмена разовой оплаты (возврат средств)"""
    if current_user.role != "admin":
        flash("Доступ запрещён", "error")
        return redirect("/admin")

    order = db.session.get(Order, order_id)
    if not order:
        flash("Заказ не найден", "error")
        return redirect("/admin/payments")

    if order.status != "paid" or order.is_collected:
        flash("Заказ нельзя отменить (уже выдан или отменён)", "error")
        return redirect("/admin/payments")

    student = db.session.get(User, order.student_id)
    if not student:
        flash("Ученик не найден", "error")
        return redirect("/admin/payments")

    # Возврат средств
    refund_amount = order.meal_price if order.meal_price else 0.0
    student.balance += refund_amount

    # Отмена заказа
    order.status = "cancelled"

    # ЛОГИРОВАНИЕ (ИСПРАВЛЕНО: action_type → reason)
    log = DeletionLog(
        user_id=current_user.id,
        user_email=current_user.email,
        user_full_name=current_user.full_name,
        deleted_by_admin_id=current_user.id,
        deleted_by_admin_email=current_user.email,
        refund_amount=refund_amount,
        reason=f'Администратор {current_user.full_name} отменил разовую оплату #{order.id} ученика {student.full_name}. Возвращено {refund_amount:.2f} ₽.'
    )
    db.session.add(log)

    db.session.commit()

    # Уведомление ученику
    create_notification(
        user_id=student.id,
        title="💰 Возврат средств",
        message=f"Администратор отменил оплату {'завтрака' if order.meal_type == 'breakfast' else 'обеда'} на {DAY_NAMES_RU.get(order.day_of_week, order.day_of_week)}. Возвращено {refund_amount:.2f} ₽.",
        type="info"
    )

    flash(f"✅ Оплата отменена. Возвращено {refund_amount:.2f} ₽ ученику {student.full_name}", "success")
    return redirect("/admin/payments")


@routes.route("/admin/payment/add", methods=["POST"])
@login_required
def admin_add_payment():
    """Добавление оплаты (пополнение баланса или создание заказа)"""
    if current_user.role != "admin":
        flash("Доступ запрещён", "error")
        return redirect("/admin/payments")

    student_id = request.form.get("student_id", type=int)
    amount = request.form.get("amount", type=float)
    payment_type = request.form.get("payment_type")

    if not student_id:
        flash("Неверные данные для оплаты", "error")
        return redirect("/admin/payments")

    student = db.session.get(User, student_id)
    if not student or student.role != "student" or not student.is_active:
        flash("Ученик не найден или неактивен", "error")
        return redirect("/admin/payments")

    if payment_type == "balance":
        # === ПОПОЛНЕНИЕ БАЛАНСА - требует сумму ===
        if not amount or amount <= 0:
            flash("Неверная сумма для пополнения", "error")
            return redirect("/admin/payments")

        old_balance = student.balance
        student.balance += amount
        db.session.commit()
        create_notification(
            user_id=student.id,
            title="💰 Баланс пополнен",
            message=f"Администратор пополнил ваш баланс на {amount:.2f} ₽. Было: {old_balance:.2f} ₽, стало: {student.balance:.2f} ₽",
            type="success"
        )
        flash(f"✅ Баланс ученика {student.full_name} пополнен на {amount:.2f} ₽", "success")
        return redirect("/admin/payments")

    elif payment_type == "order":
        # === СОЗДАНИЕ ЗАКАЗА - сумма не нужна, берётся из меню ===
        serving_date_str = request.form.get("serving_date")
        meal_type = request.form.get("meal_type")
        if not serving_date_str or not meal_type:
            flash("Не указана дата или тип приёма пищи", "error")
            return redirect("/admin/payments")

        try:

            serving_date = datetime.strptime(serving_date_str, "%Y-%m-%d").date()

        except ValueError:

            flash("Неверный формат даты", "error")

            return redirect("/admin/payments")

        # Проверяем, что это будний день

        if serving_date.weekday() >= 5:  # 5=сб, 6=вс

            flash("Оплата недоступна для выходных дней", "error")

            return redirect("/admin/payments")

        # Определяем день недели из даты

        days_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday", 4: "friday"}

        day_of_week = days_map[serving_date.weekday()]

        # Проверка существования меню

        meal = Meal.query.filter_by(day_of_week=day_of_week, meal_type=meal_type).first()

        if not meal:
            flash("Меню для выбранной даты и приёма не найдено", "error")

            return redirect("/admin/payments")

        # Проверка, не оплачен ли уже этот приём на эту дату

        existing_order = Order.query.filter_by(

            student_id=student_id,

            serving_date=serving_date,

            meal_type=meal_type,

            status="paid"

        ).first()

        if existing_order:
            flash(f"Этот приём пищи уже оплачен на {serving_date.strftime('%d.%m.%Y')}", "error")

            return redirect("/admin/payments")

        # === КЛЮЧЕВАЯ ПРОВЕРКА: достаточно ли средств на балансе? ===

        if student.balance < meal.price:
            flash(

                f"Недостаточно средств на балансе ученика {student.full_name}. "

                f"Требуется: {meal.price:.2f} ₽, доступно: {student.balance:.2f} ₽. "

                f"Пополните баланс ученика перед оплатой.",

                "error"

            )

            return redirect("/admin/payments")

        # === БАЛАНС ДОСТАТОЧНЫЙ - СПИСЫВАЕМ ДЕНЬГИ И СОЗДАЁМ ЗАКАЗ ===

        old_balance = student.balance

        student.balance -= meal.price

        # Собираем ингредиенты для фиксации в заказе

        ingredients_list = []

        for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():

            ing = db.session.get(Ingredient, mi.ingredient_id)

            if ing:
                ingredients_list.append({

                    "name": ing.name,

                    "qty": mi.quantity,

                    "unit": mi.unit

                })

        # Создаём заказ

        order = Order(

            student_id=student_id,

            day_of_week=day_of_week,

            meal_type=meal_type,

            serving_date=serving_date,

            status="paid",

            paid_at=datetime.utcnow(),

            meal_name=meal.name,

            meal_price=meal.price,

            meal_ingredients=json.dumps(ingredients_list, ensure_ascii=False)

        )

        db.session.add(order)

        db.session.commit()

        # Уведомление ученику

        create_notification(

            user_id=student.id,

            title="✅ Оплата добавлена администратором",

            message=f"{'Завтрак' if meal_type == 'breakfast' else 'Обед'} на {serving_date.strftime('%d.%m.%Y')} оплачен администратором. Сумма: {meal.price:.2f} ₽",

            type="success"

        )

        flash(

            f"✅ Оплата для {student.full_name} на {serving_date.strftime('%d.%m.%Y')} создана. "

            f"Списано: {meal.price:.2f} ₽. Новый баланс: {student.balance:.2f} ₽",

            "success"

        )

        return redirect("/admin/payments")


@routes.route("/api/menu/<day_of_week>/<meal_type>")
@login_required
def get_menu_info(day_of_week, meal_type):
    """API: получение информации о меню для конкретного дня и приёма пищи"""
    if current_user.role != "admin":
        return jsonify({"success": False, "error": "Доступ запрещён"}), 403

    meal = Meal.query.filter_by(day_of_week=day_of_week, meal_type=meal_type).first()

    if not meal:
        return jsonify({"success": False, "error": "Меню не найдено"}), 404

    return jsonify({
        "success": True,
        "meal_name": meal.name,
        "price": float(meal.price) if meal.price else 0.0,
        "day_of_week": day_of_week,
        "meal_type": meal_type
    })


# routes.py - добавить новый маршрут:
@routes.route("/student/confirm_consumption/<int:order_id>", methods=["POST"])
@login_required
def confirm_consumption(order_id):
    """Ученик подтверждает получение питания"""
    if current_user.role != "student":
        return redirect("/student")

    order = Order.query.get(order_id)
    if not order:
        flash("Заказ не найден", "error")
        return redirect("/student")

    # Проверка: заказ принадлежит ученику
    if order.student_id != current_user.id:
        flash("Это не ваш заказ", "error")
        return redirect("/student")

    # Проверка: заказ должен быть оплачен
    if order.status != "paid":
        flash("Заказ не оплачен", "error")
        return redirect("/student")

    # Проверка: повар уже выдал питание
    if not order.is_collected:
        flash("❌ Питание ещё не выдано поваром. Обратитесь к повару в столовой.", "error")
        return redirect("/student")

    # Проверка: ученик ещё не подтверждал
    if order.student_confirmed:
        flash("✅ Вы уже подтвердили получение этого питания.", "info")
        return redirect("/student")

    # Подтверждаем получение
    order.student_confirmed = True
    order.confirmed_at = datetime.utcnow()
    db.session.commit()

    # Уведомление повару
    cook_users = User.query.filter_by(role="cook").all()
    for cook in cook_users:
        create_notification(
            user_id=cook.id,
            title="✅ Питание подтверждено учеником",
            message=f"Ученик {current_user.full_name} подтвердил получение {'завтрака' if order.meal_type == 'breakfast' else 'обеда'} на {DAY_NAMES_RU.get(order.day_of_week, order.day_of_week)} ({order.serving_date.strftime('%d.%m')}).",
            type="success",
            order_id=order.id
        )

    flash("✅ Питание успешно подтверждено! Теперь вы можете оставить отзыв.", "success")
    return redirect("/student")


@routes.route("/logout")
def logout():
    logout_user()
    return redirect("/")