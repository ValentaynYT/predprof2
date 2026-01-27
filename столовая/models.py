# models.py

from database import db
from flask_login import UserMixin
from datetime import datetime

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255))
    email = db.Column(db.String(255), unique=True)
    password = db.Column(db.String(255))
    role = db.Column(db.String(20))
    balance = db.Column(db.Float, default=0.0)  # ← НОВОЕ ПОЛЕ
    has_subscription = db.Column(db.Boolean, default=False)  # ← НОВОЕ ПОЛЕ
class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20), default="г")

class Meal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(20))
    meal_type = db.Column(db.String(20))
    name = db.Column(db.String(255))
    price = db.Column(db.Float)

class MealIngredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meal_id = db.Column(db.Integer, db.ForeignKey('meal.id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), default="г")

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    day_of_week = db.Column(db.String(20))
    meal_type = db.Column(db.String(20))
    status = db.Column(db.String(20), default="paid")
    is_collected = db.Column(db.Boolean, default=False)
    serving_date = db.Column(db.Date)                     # дата приёма пищи
    consumed_at = db.Column(db.DateTime, nullable=True)   # ✅ ВРЕМЯ ВЫДАЧИ
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)  # время создания заказа
    paid_at = db.Column(db.DateTime, nullable=True)

    @property
    def consumed(self):
        return self.is_collected and self.consumed_at is not None

    @consumed.setter
    def consumed(self, value):
        if value:
            self.is_collected = True
            if self.consumed_at is None:
                self.consumed_at = datetime.utcnow()
        else:
            self.is_collected = False
            self.consumed_at = None

class Allergy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.Text)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    day_of_week = db.Column(db.String(20))
    meal_type = db.Column(db.String(20))
    text = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PurchaseRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cook_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product = db.Column(db.String(100))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20), default="г")
    status = db.Column(db.String(20), default="pending")

class MenuChangeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cook_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending / approved / rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # JSON-поля с данными меню и ингредиентами
    menu_data = db.Column(db.Text)  # serialized JSON
    ingredients_summary = db.Column(db.Text)  # {"Молоко": {"quantity": 5000, "unit": "мл"}, ...}