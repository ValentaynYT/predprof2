# app.py

from flask import Flask
from flask_login import LoginManager
from database import db
from models import User, Meal, Ingredient, MealIngredient, Product
from routes import routes

app = Flask(__name__)
app.secret_key = "secret123"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school_food.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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

    # === Ингредиенты ===
    if Ingredient.query.count() == 0:
        ingredients = [
            "Овсяные хлопья", "Вода", "Чай", "Хлеб", "Масло сливочное",
            "Свёкла", "Капуста", "Картофель", "Морковь", "Лук", "Говядина", "Котлеты", "Компот (сухофрукты)",
            "Творог", "Ягоды", "Молоко", "Булочка",
            "Тыква", "Курица", "Рис", "Сок",
            "Манка", "Какао", "Печенье",
            "Щавель", "Гречка", "Рыба", "Кисель",
            "Яйца", "Помидоры", "Тосты",
            "Горох", "Макароны", "Фарш", "Овощи", "Мясо"
        ]
        for name in ingredients:
            db.session.add(Ingredient(name=name))
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
    app.run(debug=True)