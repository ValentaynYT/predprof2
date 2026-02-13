# app.py

from flask import Flask
from flask_login import LoginManager
from database import db
from models import User, Meal, Ingredient, MealIngredient, Product, FlexibleSubscription
from routes import routes
import os
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
#csrf = CSRFProtect(app)  # Включаем защиту
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school_food.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# === СЕКРЕТНЫЕ КОДЫ ДОСТУПА ===
ACCESS_CODES = {
    "student": "STUDENT2026",  # Общий код для всех учеников
    "cook": "COOK@Kitchen2026",  # Специальный код для поваров
    "admin": "ADMIN#Super2026!"  # Секретный код для администраторов
}
app.config['ACCESS_CODES'] = ACCESS_CODES

# Папка для аватарок
AVATARS_FOLDER = os.path.join('static', 'avatars')
os.makedirs(AVATARS_FOLDER, exist_ok=True)
app.config['AVATARS_FOLDER'] = AVATARS_FOLDER

db.init_app(app)

login_manager = LoginManager(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

app.register_blueprint(routes)

with app.app_context():
    db.create_all()

    # === Меню ===
    if Meal.query.count() == 0:
        meals_data = [
            ("monday", "breakfast", "Овсяная каша на воде, чай, хлеб с маслом", 50.0),
            ("monday", "lunch", "Борщ, картофельное пюре с котлетой, компот из сухофруктов", 100.0),
            ("tuesday", "breakfast", "Творог с ягодами, молоко, булочка", 50.0),
            ("tuesday", "lunch", "Суп-пюре из тыквы, плов с курицей, фруктовый сок", 100.0),
            ("wednesday", "breakfast", "Манная каша, какао, галетное печенье", 50.0),
            ("wednesday", "lunch", "Щи из свежей капусты, гречка с рыбными котлетами, кисель", 100.0),
            ("thursday", "breakfast", "Яичница с помидорами, чай, тосты", 50.0),
            ("thursday", "lunch", "Гороховый суп, макароны по-флотски, компот", 100.0),
            ("friday", "breakfast", "Рисовая молочная каша, сок, батончик мюсли", 50.0),
            ("friday", "lunch", "Суп с фрикадельками, рагу овощное с мясом, чай", 100.0),
        ]
        for day, meal_type, name, price in meals_data:
            db.session.add(Meal(day_of_week=day, meal_type=meal_type, name=name, price=price))
        db.session.commit()

    # === Ингредиенты с ценами ===
    if Ingredient.query.count() == 0:
        ingredients_with_prices = [
            ("Овсяные хлопья", 0.03),  # 30 ₽/кг → 0.03 ₽/г
            ("Вода", 0.01),  # условно
            ("Чай", 0.5),  # 50 ₽/пакетик
            ("Хлеб", 0.1),  # 100 ₽/буханка (~1 кг) → 0.1 ₽/г
            ("Масло сливочное", 0.7),  # 700 ₽/кг
            ("Свёкла", 0.04),
            ("Капуста", 0.03),
            ("Картофель", 0.025),
            ("Морковь", 0.035),
            ("Лук", 0.02),
            ("Говядина", 0.8),
            ("Котлеты", 0.9),
            ("Компот (сухофрукты)", 0.6),
            ("Творог", 0.5),
            ("Ягоды", 1.2),
            ("Молоко", 0.06),  # 60 ₽/л → 0.06 ₽/мл
            ("Булочка", 15.0),
            ("Тыква", 0.03),
            ("Курица", 0.6),
            ("Рис", 0.05),
            ("Сок", 0.1),  # 100 ₽/л → 0.1 ₽/мл
            ("Манка", 0.04),
            ("Какао", 1.0),
            ("Печенье", 10.0),
            ("Щавель", 0.15),
            ("Гречка", 0.045),
            ("Рыба", 0.9),
            ("Кисель", 0.4),
            ("Яйца", 12.0),  # за штуку
            ("Помидоры", 0.08),
            ("Тосты", 8.0),
            ("Горох", 0.04),
            ("Макароны", 0.035),
            ("Фарш", 0.75),
            ("Овощи", 0.05),
            ("Мясо", 0.75),
            ("Батончик мюсли", 25.0),
        ]
        for name, price in ingredients_with_prices:
            db.session.add(Ingredient(name=name, price_per_unit=price))
        db.session.commit()

    # === Связи: блюда → ингредиенты ===
    if MealIngredient.query.count() == 0:
        meal_map = {}
        for meal in Meal.query.all():
            key = (meal.day_of_week, meal.meal_type)
            meal_map[key] = meal

        ingredient_map = {ing.name: ing.id for ing in Ingredient.query.all()}

        def add_ingredients(day, meal_type, items):
            meal = meal_map.get((day, meal_type))
            if not meal:
                return
            for name, qty, unit in items:
                ing_id = ingredient_map.get(name)
                if ing_id:
                    db.session.add(MealIngredient(
                        meal_id=meal.id,
                        ingredient_id=ing_id,
                        quantity=qty,
                        unit=unit
                    ))

        add_ingredients("monday", "breakfast", [
            ("Овсяные хлопья", 50, "г"),
            ("Вода", 200, "мл"),
            ("Чай", 1, "шт"),
            ("Хлеб", 1, "шт"),
            ("Масло сливочное", 10, "г")
        ])
        add_ingredients("monday", "lunch", [
            ("Свёкла", 100, "г"),
            ("Капуста", 50, "г"),
            ("Картофель", 150, "г"),
            ("Морковь", 30, "г"),
            ("Лук", 20, "г"),
            ("Говядина", 80, "г"),
            ("Котлеты", 1, "шт"),
            ("Компот (сухофрукты)", 1, "шт")
        ])
        add_ingredients("tuesday", "breakfast", [
            ("Творог", 100, "г"),
            ("Ягоды", 30, "г"),
            ("Молоко", 200, "мл"),
            ("Булочка", 1, "шт")
        ])
        add_ingredients("tuesday", "lunch", [
            ("Тыква", 150, "г"),
            ("Курица", 100, "г"),
            ("Рис", 70, "г"),
            ("Сок", 1, "шт")
        ])
        add_ingredients("wednesday", "breakfast", [
            ("Манка", 50, "г"),
            ("Молоко", 200, "мл"),
            ("Какао", 1, "шт"),
            ("Печенье", 2, "шт")
        ])
        add_ingredients("wednesday", "lunch", [
            ("Щавель", 50, "г"),
            ("Капуста", 50, "г"),
            ("Гречка", 80, "г"),
            ("Рыба", 100, "г"),
            ("Кисель", 1, "шт")
        ])
        add_ingredients("thursday", "breakfast", [
            ("Яйца", 2, "шт"),
            ("Помидоры", 50, "г"),
            ("Чай", 1, "шт"),
            ("Тосты", 2, "шт")
        ])
        add_ingredients("thursday", "lunch", [
            ("Горох", 80, "г"),
            ("Макароны", 100, "г"),
            ("Фарш", 100, "г"),
            ("Компот", 1, "шт")
        ])
        add_ingredients("friday", "breakfast", [
            ("Рис", 50, "г"),
            ("Молоко", 200, "мл"),
            ("Сок", 1, "шт"),
            ("Батончик мюсли", 1, "шт")
        ])
        add_ingredients("friday", "lunch", [
            ("Фарш", 100, "г"),
            ("Овощи", 150, "г"),
            ("Мясо", 80, "г"),
            ("Чай", 1, "шт")
        ])

        db.session.commit()

    # === Остатки продуктов ===
    if Product.query.count() == 0:
        for ing in Ingredient.query.all():
            if ing.name in ["Яйца", "Булочка", "Печенье", "Тосты", "Батончик мюсли", "Чай", "Сок", "Компот (сухофрукты)", "Кисель"]:
                qty = 100.0
                unit = "шт"
            else:
                qty = 10000.0  # 10 кг или 10 л
                unit = "мл" if "молоко" in ing.name.lower() or "вода" in ing.name.lower() or "сок" in ing.name.lower() else "г"
            db.session.add(Product(ingredient_id=ing.id, quantity=qty, unit=unit))
        db.session.commit()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)