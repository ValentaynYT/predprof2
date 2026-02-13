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
    balance = db.Column(db.Float, default=0.0)
    has_subscription = db.Column(db.Boolean, default=False)
    class_name = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    avatar_filename = db.Column(db.String(255), default='default_avatar.png')
    allergy = db.Column(db.Text, default='')  # Пищевые особенности
    # Новое поле для архивирования
    is_active = db.Column(db.Boolean, default=True)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.Integer)  # ID админа, который удалил

class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    price_per_unit = db.Column(db.Float, default=0.0)

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

class FlexibleSubscription(db.Model):
    __tablename__ = 'flexible_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                           nullable=False)
    days_count = db.Column(db.Integer, nullable=False)
    days_config = db.Column(db.JSON, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    total_meals = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    student = db.relationship('User', backref='flexible_subscriptions')
    start_date = db.Column(db.DateTime, default=datetime.utcnow)  # Дата начала действия абонемента

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
    # фиксация рецепта на момент оплаты
    meal_name = db.Column(db.String(100))  # название блюда
    meal_price = db.Column(db.Float)  # цена на момент оплаты

    meal_ingredients = db.Column(db.Text)  # serialized JSON
    student = db.relationship('User', backref='orders')
    student_confirmed = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    # Связь с гибким абонементом
    #flexible_subscription_id = db.Column(db.Integer, db.ForeignKey('flexible_subscription.id'), nullable=True)
    # ИСТОЧНИК ОПЛАТЫ
    payment_source = db.Column(db.String(20), default='single')  # 'single' или 'flexible'

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

    @property
    def fully_consumed(self):
        """Полностью подтверждённое получение (повар + ученик)"""
        return self.is_collected and self.student_confirmed

    @fully_consumed.setter
    def fully_consumed(self, value):
        if value:
            self.is_collected = True
            self.student_confirmed = True
            if self.consumed_at is None:
                self.consumed_at = datetime.utcnow()
            if self.confirmed_at is None:
                self.confirmed_at = datetime.utcnow()

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
    week_number = db.Column(db.Integer, default=0)  # 0 = текущая неделя, 1 = следующая и т.д.
    # НОВЫЕ ПОЛЯ ДЛЯ АБСОЛЮТНОЙ ПРИВЯЗКИ
    review_year = db.Column(db.Integer, nullable=False)  # Год недели (по ISO)
    review_week_iso = db.Column(db.Integer, nullable=False)  # Номер недели по ISO (1-53)

class PurchaseRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cook_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product = db.Column(db.String(100))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20), default="г")
    status = db.Column(db.String(20), default="pending")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class WriteOff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(10), default="г")
    reason = db.Column(db.String(100), default="Порча")  # можно расширить
    cook_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ingredient = db.relationship('Ingredient', backref='write_offs')
    cook = db.relationship('User', foreign_keys=[cook_id])


# models.py

class Notification(db.Model):
    """Модель уведомлений для пользователей"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), default="info")  # info, success, warning, error
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Ссылки на связанные сущности
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    request_id = db.Column(db.Integer, db.ForeignKey('purchase_request.id'), nullable=True)

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic',
                                                      order_by='Notification.created_at.desc()'))
    order = db.relationship('Order', backref='notifications')
    purchase_request = db.relationship('PurchaseRequest', backref='notifications')

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'is_read': self.is_read,
            'created_at': self.created_at.strftime('%d.%m.%Y %H:%M')
        }


class DeletionLog(db.Model):
    """Лог удаления пользователей"""
    __tablename__ = 'deletion_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)  # ID удалённого пользователя
    user_email = db.Column(db.String(120), nullable=False)
    user_full_name = db.Column(db.String(200), nullable=False)
    deleted_by_admin_id = db.Column(db.Integer, nullable=False)  # ID админа
    deleted_by_admin_email = db.Column(db.String(120), nullable=False)
    refund_amount = db.Column(db.Float, default=0.0)  # Сумма возврата
    reason = db.Column(db.Text)  # Причина удаления (опционально)
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DeletionLog {self.user_full_name}>'