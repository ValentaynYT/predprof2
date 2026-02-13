# routes.py

from flask import Blueprint, render_template, request, redirect, jsonify, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
from models import User, Meal, Order, Allergy, Review, PurchaseRequest, Ingredient, MealIngredient, Product, MenuChangeRequest
from datetime import datetime, timedelta
import json

routes = Blueprint('routes', __name__)


def from_json(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}

# Регистрируем фильтр для Jinja2
@routes.app_template_filter('from_json')
def from_json_filter(s):
    return from_json(s)


DAY_NAMES_RU = {
    "monday": "понедельник",
    "tuesday": "вторник",
    "wednesday": "среду",
    "thursday": "четверг",
    "friday": "пятницу"
}


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


def get_date_for_day(day_of_week):
    days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
    if day_of_week not in days_map:
        return datetime.today().date()
    today = datetime.today()
    diff = days_map[day_of_week] - today.weekday()
    return (today + timedelta(days=diff)).date()


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
        if not full_name or not email or not password or role not in ["student", "cook", "admin"]:
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            return render_template("register.html")
        user = User(full_name=full_name, email=email, password=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
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
            login_user(user)
            if user.role in ["student", "cook", "admin"]:
                return redirect(f"/{user.role}")
            else:
                return redirect("/")
    return render_template("login.html")


@routes.route("/student", methods=["GET", "POST"])
@login_required
def student():
    current_balance = current_user.balance

    if current_user.role != "student":
        return redirect("/")

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
        return redirect("/student")

    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    day_names = {d: n for d, n in zip(days, ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"])}

    # === ОПРЕДЕЛЕНИЕ ТЕКУЩЕГО ДНЯ ===
    from datetime import datetime
    today = datetime.today().weekday()  # 0=понедельник, 4=пятница
    day_index_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday", 4: "friday"}
    current_day = day_index_map.get(today, None)

    meals = {day: {"breakfast": None, "lunch": None} for day in days}
    for m in Meal.query.all():
        if m.day_of_week in meals and m.meal_type in meals[m.day_of_week]:
            meals[m.day_of_week][m.meal_type] = {
                "name": m.name,
                "price": m.price
            }

    user_reviews = {(r.day_of_week, r.meal_type): r.text for r in
                    Review.query.filter_by(student_id=current_user.id).all()}

    orders = Order.query.filter_by(student_id=current_user.id).all()

    full_subscription_price = calculate_full_subscription_price()

    # === Расчёт стоимости абонемента на оставшиеся дни ===
    from datetime import datetime
    today_weekday = datetime.today().weekday()  # 0=понедельник, 4=пятница

    if today_weekday <= 4:  # будние дни
        remaining_days = ["monday", "tuesday", "wednesday", "thursday", "friday"][today_weekday:]
        full_subscription_price = 0.0
        for day in remaining_days:
            for mt in ["breakfast", "lunch"]:
                meal = Meal.query.filter_by(day_of_week=day, meal_type=mt).first()
                if meal and meal.price:
                    full_subscription_price += meal.price
    else:
        full_subscription_price = 0.0  # выходные — абонемент недоступен

    # Уже оплачено (только за оставшиеся дни)
    paid_sum = 0.0
    for order in orders:
        if order.status == "paid" and order.paid_at is not None:
            # Проверяем, что день входит в оставшиеся
            if today_weekday <= 4:
                try:
                    day_index = ["monday", "tuesday", "wednesday", "thursday", "friday"].index(order.day_of_week)
                    if day_index >= today_weekday:
                        meal = Meal.query.filter_by(
                            day_of_week=order.day_of_week,
                            meal_type=order.meal_type
                        ).first()
                        if meal and meal.price:
                            paid_sum += meal.price
                except ValueError:
                    pass  # игнорируем неизвестные дни

    remaining_subscription_price = max(0.0, full_subscription_price - paid_sum)

    order_status = {(o.day_of_week, o.meal_type): {'paid': True, 'consumed': o.is_collected} for o in orders}

    paid_count = len([o for o in orders if o.status == "paid" and o.paid_at is not None])
    consumed_count = len([o for o in orders if o.is_collected])  # ← единообразно
    total_possible = 10

    return render_template(
        "student.html",
        days=days,
        day_names=day_names,
        meals=meals,
        user_reviews=user_reviews,
        current_allergy=current_allergy,
        order_status=order_status,
        paid_count=paid_count,
        consumed_count=consumed_count,
        total_possible=total_possible,
        current_balance=current_balance,  # ← добавлено
        full_subscription_price=full_subscription_price,
        paid_sum=paid_sum,
        remaining_subscription_price=remaining_subscription_price,
        current_day=current_day

    )


@routes.route("/submit_review", methods=["POST"])
@login_required
def submit_review():
    if current_user.role != "student":
        return redirect("/")
    day = request.form.get("day")
    meal_type = request.form.get("meal_type")
    text = request.form.get("text", "").strip()
    if day and meal_type and text:
        existing = Review.query.filter_by(student_id=current_user.id, day_of_week=day, meal_type=meal_type).first()
        if existing:
            existing.text = text
        else:
            db.session.add(Review(student_id=current_user.id, day_of_week=day, meal_type=meal_type, text=text))
        db.session.commit()
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

        # === НОВАЯ ПРОВЕРКА: нельзя оплатить прошедший день ===
        today = datetime.today().weekday()  # 0=понедельник, 4=пятница
        day_order = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
        if day_order.get(day, -1) < today:
            flash("Нельзя оплатить питание за прошедший день.", "error")
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

        # Создаём заказ
        serving_date = get_date_for_day(day)
        db.session.add(Order(
            student_id=current_user.id,
            day_of_week=day,
            meal_type=meal_type,
            serving_date=serving_date,
            status="paid",
            paid_at=datetime.utcnow()
        ))
        current_user.balance -= total_price
        db.session.commit()
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

        # Создаём заказы
        for day, mt in meals_to_create:
            serving_date = get_date_for_day(day)
            db.session.add(Order(
                student_id=current_user.id,
                day_of_week=day,
                meal_type=mt,
                serving_date=serving_date,
                status="paid",
                paid_at=datetime.utcnow()
            ))

        current_user.balance -= total_price
        current_user.has_subscription = True  # ← помечаем, что абонемент куплен
        db.session.commit()

        if len(unpaid_keys) == len(remaining_days) * 2:
            flash(f"Абонемент на оставшиеся дни ({len(remaining_days)}) успешно оплачен!", "success")
        else:
            flash(f"Абонемент на оставшиеся приёмы оплачен! Списано: {total_price:.2f} ₽", "success")
        return redirect("/student")

    else:
        flash("Неверный тип оплаты.", "error")
        return redirect("/student")


@routes.route("/cook", methods=["GET"])
@login_required
def cook():
    if current_user.role != "cook":
        return redirect("/")

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
        if order.is_collected:
            students_data[student.id]['completed'].append(entry)
        else:
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

    return render_template(
        "cook.html",
        students=sorted_students,
        total_students=total_students,
        all_ingredients=all_ingredients,
        need_and_stock=need_and_stock  # ← передаём данные о запасах
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

    ingredient = Ingredient.query.get(ingredient_id)
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
    return redirect("/cook")


# routes.py — обновлённый маршрут /admin

@routes.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if current_user.role != "admin":
        return redirect("/")

    # === Обработка POST-запросов: заявки на закупку ИЛИ на меню ===
    if request.method == "POST":
        # --- Заявка на закупку ---
        req_id = request.form.get("id")
        new_status = request.form.get("status")
        if req_id and new_status in ["approved", "rejected"]:
            req = PurchaseRequest.query.get(req_id)
            if req:
                req.status = new_status
                if new_status == "approved":
                    product_name = req.product.split(" (")[0]
                    ingredient = Ingredient.query.filter_by(name=product_name).first()
                    if ingredient:
                        product = Product.query.filter_by(ingredient_id=ingredient.id).first()
                        if product:
                            product.quantity += req.quantity
                        else:
                            db.session.add(Product(
                                ingredient_id=ingredient.id,
                                quantity=req.quantity,
                                unit=req.unit or "г"
                            ))
                db.session.commit()
                return redirect("/admin")

        # --- Заявка на изменение меню ---
        menu_req_id = request.form.get("menu_req_id")
        menu_status = request.form.get("menu_status")
        if menu_req_id and menu_status in ["approved", "rejected"]:
            req = MenuChangeRequest.query.get(menu_req_id)
            if req:
                req.status = menu_status
                if menu_status == "approved":
                    # 1. Обновляем меню
                    menu_data = json.loads(req.menu_data)
                    all_ingredients = {ing.name: ing.id for ing in Ingredient.query.all()}
                    for day, meals in menu_data.items():
                        for meal_type, data in meals.items():
                            meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
                            if not meal:
                                meal = Meal(day_of_week=day, meal_type=meal_type)
                                db.session.add(meal)
                            meal.name = data["name"]
                            meal.price = data["price"]
                            MealIngredient.query.filter_by(meal_id=meal.id).delete()
                            for ing in data["ingredients"]:
                                name = ing["name"]
                                if name not in all_ingredients:
                                    new_ing = Ingredient(name=name)
                                    db.session.add(new_ing)
                                    db.session.flush()
                                    all_ingredients[name] = new_ing.id
                                db.session.add(MealIngredient(
                                    meal_id=meal.id,
                                    ingredient_id=all_ingredients[name],
                                    quantity=ing["quantity"],
                                    unit=ing["unit"]
                                ))
                    # 2. Пополняем склад
                    summary = json.loads(req.ingredients_summary)
                    for full_name, data in summary.items():
                        product_name = full_name.split(" (")[0]
                        unit = data["unit"]
                        quantity = data["quantity"]
                        ingredient = Ingredient.query.filter_by(name=product_name).first()
                        if ingredient:
                            product = Product.query.filter_by(ingredient_id=ingredient.id).first()
                            if product:
                                product.quantity += quantity
                            else:
                                db.session.add(Product(
                                    ingredient_id=ingredient.id,
                                    quantity=quantity,
                                    unit=unit
                                ))
                    flash("Меню одобрено и обновлено! Продукты пополнены.", "success")
                db.session.commit()
                return redirect("/admin")

    # === Сбор статистики ===
    total_students = User.query.filter_by(role="student").count()
    paid_orders = Order.query.filter_by(status="paid").all()
    total_paid = len(paid_orders)
    collected_orders = Order.query.filter_by(status="paid", is_collected=True).all()
    total_consumed = len(collected_orders)

    student_stats = []
    students = User.query.filter_by(role="student").all()
    for student in students:
        paid = Order.query.filter_by(student_id=student.id, status="paid").count()
        consumed = Order.query.filter_by(student_id=student.id, status="paid", is_collected=True).count()
        attendance_pct = round((consumed / 10) * 100) if 10 > 0 else 0
        student_stats.append({
            "student": student,
            "paid": paid,
            "consumed": consumed,
            "attendance_pct": min(100, attendance_pct)
        })

    # === Заявки ===
    requests = PurchaseRequest.query.all()
    menu_requests = MenuChangeRequest.query.filter_by(status="pending").all()

    return render_template(
        "admin.html",
        total_paid=total_paid,
        total_consumed=total_consumed,
        total_students=total_students,
        student_stats=student_stats,
        requests=requests,
        menu_requests=menu_requests
    )


# routes.py — добавьте в конец или рядом с cook-функциями

# routes.py

@routes.route("/cook/mark_collected", methods=["POST"])
@login_required
def mark_collected():
    if current_user.role != "cook":
        return redirect("/")

    order_id = request.form.get("order_id")
    if not order_id:
        flash("Не указан заказ.", "error")
        return redirect("/cook")

    order = Order.query.get(order_id)
    if not order or order.is_collected:
        flash("Заказ не найден или уже выдан.", "warning")
        return redirect("/cook")

    # Находим блюдо
    meal = Meal.query.filter_by(
        day_of_week=order.day_of_week,
        meal_type=order.meal_type
    ).first()

    if not meal:
        flash("Блюдо не найдено в меню. Выдача невозможна.", "error")
        return redirect("/cook")

    # Проверяем наличие всех ингредиентов
    ingredients_used = MealIngredient.query.filter_by(meal_id=meal.id).all()
    insufficient = []

    for used in ingredients_used:
        product = Product.query.filter_by(ingredient_id=used.ingredient_id).first()
        if not product or product.quantity < used.quantity:
            ingredient_name = Ingredient.query.get(used.ingredient_id).name
            insufficient.append(f"{ingredient_name} (нужно {used.quantity}{used.unit}, есть {product.quantity if product else 0}{used.unit})")

    if insufficient:
        msg = "Недостаточно продуктов для выдачи:\n" + "\n".join(insufficient)
        flash(msg, "error")
        return redirect("/cook")

    # Списываем ингредиенты
    for used in ingredients_used:
        product = Product.query.filter_by(ingredient_id=used.ingredient_id).first()
        if product:
            product.quantity -= used.quantity

    # Отмечаем выдачу
    order.is_collected = True
    order.consumed_at = datetime.utcnow()
    db.session.commit()

    flash("Заказ успешно выдан и продукты списаны.", "success")
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

        for item in requests_data:
            product_name = item.get("product")
            quantity = item.get("quantity")
            unit = item.get("unit", "г")

            # Валидация
            if not isinstance(product_name, str) or not product_name.strip():
                continue  # или вернуть ошибку — по желанию
            if not isinstance(quantity, (int, float)) or quantity <= 0:
                continue

            # Формируем имя продукта: "Молоко (л)"
            full_product_name = f"{product_name.strip()} ({unit})" if unit else product_name.strip()

            db.session.add(PurchaseRequest(
                cook_id=current_user.id,
                product=full_product_name,
                quantity=float(quantity),
                unit=unit,
                status="pending"
            ))

        db.session.commit()
        return jsonify({"success": True, "message": "Заявка отправлена"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Ошибка при сохранении заявки"}), 500


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
    except (ValueError, TypeError):
        pass
    return redirect("/student")


@routes.route("/cook/menu", methods=["GET", "POST"])
@login_required
def cook_menu():
    if current_user.role != "cook":
        return redirect("/cook")

    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    day_names = {d: n for d, n in zip(days, ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"])}

    if request.method == "POST":
        # Собираем данные меню (как раньше)
        menu_data = {}
        all_ingredients = {ing.name: ing.id for ing in Ingredient.query.all()}
        total_students = User.query.filter_by(role="student").count() or 1

        for day in days:
            menu_data[day] = {}
            for meal_type in ["breakfast", "lunch"]:
                name = request.form.get(f"{day}_{meal_type}_name", "").strip()
                price_str = request.form.get(f"{day}_{meal_type}_price", "").strip()
                try:
                    price = float(price_str) if price_str else 0.0
                except ValueError:
                    price = 0.0

                ingredients = []
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
                    ingredients.append({"name": ing_name, "quantity": qty, "unit": unit})
                    idx += 1

                menu_data[day][meal_type] = {
                    "name": name,
                    "price": price,
                    "ingredients": ingredients
                }

        # === Агрегируем ингредиенты по всему меню × кол-во учеников ===
        from collections import defaultdict
        summary = defaultdict(lambda: {"quantity": 0.0, "unit": "г"})
        for day in days:
            for meal_type in ["breakfast", "lunch"]:
                for ing in menu_data[day][meal_type]["ingredients"]:
                    key = (ing["name"], ing["unit"])
                    summary[key]["quantity"] += ing["quantity"] * total_students
                    summary[key]["unit"] = ing["unit"]

        # Преобразуем в плоский dict: {"Молоко (мл)": {"quantity": 5000, "unit": "мл"}, ...}
        flat_summary = {}
        for (name, unit), data in summary.items():
            full_name = f"{name} ({unit})"
            flat_summary[full_name] = {"quantity": data["quantity"], "unit": unit}

        # Сохраняем заявку
        db.session.add(MenuChangeRequest(
            cook_id=current_user.id,
            menu_data=json.dumps(menu_data, ensure_ascii=False),
            ingredients_summary=json.dumps(flat_summary, ensure_ascii=False)
        ))
        db.session.commit()
        flash("Меню отправлено администратору на согласование!", "success")
        return redirect("/cook")

    # === GET: загрузка текущего меню ===
    meals_data = {}
    for day in days:
        meals_data[day] = {"breakfast": {}, "lunch": {}}
        for meal_type in ["breakfast", "lunch"]:
            meal = Meal.query.filter_by(day_of_week=day, meal_type=meal_type).first()
            if meal:
                ingredients = []
                for mi in MealIngredient.query.filter_by(meal_id=meal.id).all():
                    ing = Ingredient.query.get(mi.ingredient_id)
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
        meals=meals_data,
        is_cook=True
    )


@routes.route("/logout")
def logout():
    logout_user()
    return redirect("/")