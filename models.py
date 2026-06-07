from datetime import datetime
from zoneinfo import ZoneInfo
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# 时区配置
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _get_shanghai_time():
    """获取当前上海时间（naive datetime）"""
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)  # 是否启用


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    qtype = db.Column(db.String(20), nullable=False)  # single / multiple / blank
    stem = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.String(300), nullable=False)
    explanation = db.Column(db.Text, default="")
    ai_explanation = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)

    category = db.relationship("Category", backref=db.backref("questions", lazy=True))


class Choice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    option_key = db.Column(db.String(10), nullable=False)
    option_text = db.Column(db.Text, nullable=False)

    question = db.relationship("Question", backref=db.backref("choices", lazy=True))


class PracticeProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    answered = db.Column(db.Boolean, default=False)
    is_correct = db.Column(db.Boolean, default=None, nullable=True)
    answer = db.Column(db.String(300), default="")
    last_answered_at = db.Column(db.DateTime, default=_get_shanghai_time)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_user_question"),)


class WrongQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_wrong"),)

    question = db.relationship("Question")


class ExamSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    correct_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Float, default=0.0)
    passed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="in_progress")
    scope = db.Column(db.String(20), default="category")
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)

    category = db.relationship("Category")


class ExamQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("exam_session.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    user_answer = db.Column(db.String(300), default="")
    is_correct = db.Column(db.Boolean, default=False)

    session = db.relationship("ExamSession", backref=db.backref("exam_questions", lazy=True))
    question = db.relationship("Question")


class WrongPracticeSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    current_index = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="in_progress")
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)


class WrongPracticeQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("wrong_practice_session.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    user_answer = db.Column(db.String(300), default="")
    is_correct = db.Column(db.Boolean, default=False)

    session = db.relationship(
        "WrongPracticeSession", backref=db.backref("wrong_practice_questions", lazy=True)
    )
    question = db.relationship("Question")


class RandomPracticeSession(db.Model):
    """随机练习会话"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    current_index = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="in_progress")
    created_at = db.Column(db.DateTime, default=_get_shanghai_time)


class RandomPracticeQuestion(db.Model):
    """随机练习题目"""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("random_practice_session.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    user_answer = db.Column(db.String(300), default="")
    is_correct = db.Column(db.Boolean, default=None, nullable=True)
    is_wrong_review = db.Column(db.Boolean, default=False)
    has_submitted = db.Column(db.Boolean, default=False)

    session = db.relationship(
        "RandomPracticeSession", backref=db.backref("random_practice_questions", lazy=True)
    )
    question = db.relationship("Question")


class AnkiCard(db.Model):
    """Anki 间隔复习卡片状态"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    interval_days = db.Column(db.Float, default=0.0)
    ease = db.Column(db.Float, default=2.5)
    repetitions = db.Column(db.Integer, default=0)
    next_review_at = db.Column(db.DateTime, default=_get_shanghai_time)
    last_reviewed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_anki_card"),)

    question = db.relationship("Question")


class AnkiReviewLog(db.Model):
    """Anki 每次评分的复习记录"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    rating = db.Column(db.String(10), nullable=False)
    reviewed_at = db.Column(db.DateTime, default=_get_shanghai_time, nullable=False, index=True)

    question = db.relationship("Question")