from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, login_required, current_user
from sqlalchemy import inspect as sqlalchemy_inspect, text as sql_text
from markupsafe import Markup

# 导入自定义模块
from models import db, User, Category, Question
from utils import render_markdown, render_stem, render_explanation, render_markdown_with_blanks
from config import Config

# 导入路由蓝图
from routes.auth import auth_bp
from routes.practice import practice_bp
from routes.wrong import wrong_bp
from routes.exam import exam_bp
from routes.random_practice import random_practice_bp
from routes.anki import anki_bp
from routes.admin import admin_bp

# 创建 Flask 应用
app = Flask(__name__)
app.config.from_object(Config)

# 初始化扩展
db.init_app(app)

# 初始化 LoginManager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# 注册蓝图
app.register_blueprint(auth_bp)
app.register_blueprint(practice_bp)
app.register_blueprint(wrong_bp)
app.register_blueprint(exam_bp)
app.register_blueprint(random_practice_bp)
app.register_blueprint(anki_bp)
app.register_blueprint(admin_bp)


# ==================== 首页和基础路由 ====================
@app.route("/")
@login_required
def index():
    categories = Category.query.order_by(Category.sort_order.asc(), Category.name.asc()).all()
    return render_template("index.html", categories=categories)


# ==================== 模板过滤器 ====================
@app.template_filter("render_markdown")
def template_render_markdown(text: str) -> Markup:
    return render_markdown(text)


@app.template_filter("render_stem")
def template_render_stem(stem: str) -> Markup:
    return render_stem(stem)


@app.template_filter("render_explanation")
def template_render_explanation(explanation: str) -> Markup:
    return render_explanation(explanation)


@app.template_filter("render_markdown_with_blanks")
def template_render_markdown_with_blanks(text: str) -> Markup:
    return render_markdown_with_blanks(text)


# ==================== 数据库初始化 ====================
def init_db():
    with app.app_context():
        db.create_all()
        inspector = sqlalchemy_inspect(db.engine)

        # 检查并修复 practice_progress 表的 category_id 约束
        practice_progress_columns = [col["name"] for col in inspector.get_columns("practice_progress")]
        
        # 如果 category_id 存在且是 NOT NULL，需要重建表
        if "category_id" in practice_progress_columns:
            # 检查是否允许 NULL
            for col in inspector.get_columns("practice_progress"):
                if col["name"] == "category_id" and not col["nullable"]:
                    # 需要重建表，移除 NOT NULL 约束
                    try:
                        # 备份数据
                        old_data = db.session.execute(
                            sql_text("SELECT id, user_id, question_id, category_id, answered, is_correct, answer, last_answered_at FROM practice_progress")
                        ).fetchall()
                        
                        # 删除旧表
                        db.session.execute(sql_text("DROP TABLE practice_progress"))
                        db.session.commit()
                        
                        # 重新创建表（使用新的模型定义）
                        db.create_all()
                        db.session.commit()
                        
                        # 恢复数据（category_id 设为 NULL）
                        for row in old_data:
                            db.session.execute(
                                sql_text("""
                                    INSERT INTO practice_progress 
                                    (id, user_id, question_id, category_id, answered, is_correct, answer, last_answered_at) 
                                    VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                                """),
                                (row[0], row[1], row[2], row[4], row[5], row[6], row[7])
                            )
                        db.session.commit()
                        print("已修复 practice_progress 表的 category_id 约束")
                    except Exception as e:
                        print(f"修复表结构失败: {e}")
                        db.session.rollback()
                    break
        
        # 检查并添加 practice_progress 表的其他缺失列
        practice_progress_columns = [col["name"] for col in inspector.get_columns("practice_progress")]
        if "question_id" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN question_id INTEGER")
            )
            db.session.commit()
        if "category_id" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN category_id INTEGER")
            )
            db.session.commit()
        if "answered" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN answered BOOLEAN DEFAULT 0")
            )
            db.session.commit()
        if "is_correct" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN is_correct BOOLEAN")
            )
            db.session.commit()
        if "answer" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN answer VARCHAR(300)")
            )
            db.session.commit()
        if "last_answered_at" not in practice_progress_columns:
            db.session.execute(
                sql_text("ALTER TABLE practice_progress ADD COLUMN last_answered_at DATETIME")
            )
            db.session.commit()

        # 检查并添加 user 表的 created_at 列
        user_columns = [col["name"] for col in inspector.get_columns("user")]
        if "created_at" not in user_columns:
            db.session.execute(
                sql_text("ALTER TABLE user ADD COLUMN created_at DATETIME")
            )
            db.session.commit()

        # 检查并添加 category 表的 sort_order 列
        category_columns = [col["name"] for col in inspector.get_columns("category")]
        if "sort_order" not in category_columns:
            db.session.execute(
                sql_text("ALTER TABLE category ADD COLUMN sort_order INTEGER DEFAULT 0")
            )
            db.session.commit()

        # 检查并添加 exam_session 表的 scope 列
        exam_session_columns = [col["name"] for col in inspector.get_columns("exam_session")]
        if "scope" not in exam_session_columns:
            db.session.execute(
                sql_text("ALTER TABLE exam_session ADD COLUMN scope VARCHAR(20) DEFAULT 'category'")
            )
            db.session.commit()
        
        # 检查并添加 question 表的 ai_explanation 列
        question_columns = [col["name"] for col in inspector.get_columns("question")]
        if "ai_explanation" not in question_columns:
            db.session.execute(
                sql_text("ALTER TABLE question ADD COLUMN ai_explanation TEXT")
            )
            db.session.commit()
        
        # 检查并添加 random_practice_question 表的 is_wrong_review 列
        random_practice_question_columns = [col["name"] for col in inspector.get_columns("random_practice_question")]
        if "is_wrong_review" not in random_practice_question_columns:
            db.session.execute(
                sql_text("ALTER TABLE random_practice_question ADD COLUMN is_wrong_review BOOLEAN DEFAULT 0")
            )
            db.session.commit()
        
        # 检查并添加 random_practice_question 表的 has_submitted 列
        if "has_submitted" not in random_practice_question_columns:
            db.session.execute(
                sql_text("ALTER TABLE random_practice_question ADD COLUMN has_submitted BOOLEAN DEFAULT 0")
            )
            db.session.commit()
        
        # 创建默认管理员用户
        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", is_admin=True)
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()


if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)