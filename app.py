import json
import random
import re
import html
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import text as sql_text
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from markupsafe import Markup, escape


app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-in-production"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///exam.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(300), default="")
    sort_order = db.Column(db.Integer, default=0)


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    qtype = db.Column(db.String(20), nullable=False)  # single / multiple / blank
    stem = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.String(300), nullable=False)  # A or A,C or text
    explanation = db.Column(db.Text, default="")
    ai_explanation = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("Category", backref=db.backref("questions", lazy=True))


class Choice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    option_key = db.Column(db.String(10), nullable=False)  # A/B/C...
    option_text = db.Column(db.Text, nullable=False)

    question = db.relationship("Question", backref=db.backref("choices", lazy=True))


class PracticeProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    current_index = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint("user_id", "category_id", name="uq_progress"),)


class UserQuestionStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    answered = db.Column(db.Boolean, default=False)
    is_correct = db.Column(db.Boolean, default=False)
    answer = db.Column(db.String(300), default="")
    last_answered_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_user_question"),)


class WrongQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_wrong"),)


class ExamSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    total_count = db.Column(db.Integer, nullable=False)
    correct_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Float, default=0.0)
    passed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="in_progress")
    scope = db.Column(db.String(20), default="category")  # category / all
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.template_filter("render_stem")
def render_stem(stem: str) -> str:
    # 将题干里的占位符和 HTML 实体渲染为可见效果
    s = str(stem or "")
    s = s.replace("{blank}", "(_____)")
    s = s.replace("&nbsp;", "\u00A0").replace("&nbsp", "\u00A0")
    # 标题允许直接渲染 HTML（如 <img>、<span> 等）
    return Markup(s)


@app.template_filter("render_explanation")
def render_explanation(explanation: str) -> Markup:
    """
    把题目解析中的 <BR> / <br/> <br /> 等，渲染为真正换行 <br>。
    同时支持 <img> 等 HTML 标签的安全渲染。
    安全策略：对 br 和 img 标签做特殊保护，其他内容正常转义。
    """
    raw = str(explanation or "")
    raw = raw.strip()
    if not raw:
        raw = "暂无解析"

    # 处理可能的"二次编码"（例如 &amp;lt;BR&amp;gt;）
    raw = html.unescape(raw)

    # 提取并保护 <img> 标签
    img_placeholder_map = {}
    img_counter = 0
    
    def save_img(match):
        nonlocal img_counter
        placeholder = f"__EXAM_RENDER_IMG_{img_counter}__"
        img_placeholder_map[placeholder] = match.group(0)
        img_counter += 1
        return placeholder
    
    # 保存所有 img 标签
    raw = re.sub(r'<\s*img[^>]*>', save_img, raw, flags=re.I)
    
    # 也保存可能存在的其他需要直接渲染的标签（如 span, div 等）
    # 如果只需要图片支持，可以注释掉下面这部分
    other_html_placeholder_map = {}
    other_html_counter = 0
    
    def save_other_html(match):
        nonlocal other_html_counter
        tag_match = re.match(r'<(\w+)', match.group(0))
        if tag_match and tag_match.group(1).lower() in ['span', 'div', 'p', 'strong', 'em', 'b', 'i', 'u']:
            placeholder = f"__EXAM_RENDER_HTML_{other_html_counter}__"
            other_html_placeholder_map[placeholder] = match.group(0)
            other_html_counter += 1
            return placeholder
        return match.group(0)
    
    raw = re.sub(r'<\s*(span|div|p|strong|em|b|i|u)[^>]*>.*?<\s*/\s*\1\s*>', save_other_html, raw, flags=re.I | re.S)

    placeholder = "__EXAM_RENDER_EXPLANATION_BR__"
    # 1) 真实标签形式：<br> <br/> <br />（大小写/空格都兼容）
    raw = re.sub(r"<\s*br\s*/?\s*>", placeholder, raw, flags=re.I)
    # 2) 实体形式：&lt;br&gt; &lt;br/&gt; 等
    raw = re.sub(r"&lt;\s*br\s*/?\s*&gt;", placeholder, raw, flags=re.I)

    escaped = str(escape(raw))
    # 把占位符恢复为真正 <br>
    escaped = escaped.replace(placeholder, "<br>")

    # 换行字符也统一转为 <br>
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")

    # &nbsp; 也做兼容：escape 之后会变成 &amp;nbsp;
    escaped = escaped.replace("&amp;nbsp;", "\u00A0").replace("&amp;nbsp", "\u00A0")
    
    # 恢复 img 标签
    for placeholder, img_tag in img_placeholder_map.items():
        escaped = escaped.replace(escape(placeholder), img_tag)
    
    # 恢复其他 HTML 标签
    for placeholder, html_tag in other_html_placeholder_map.items():
        escaped = escaped.replace(escape(placeholder), html_tag)

    return Markup(escaped)


def normalize_answer(qtype: str, raw_answer):
    if qtype == "multiple":
        if isinstance(raw_answer, list):
            values = raw_answer
        elif raw_answer:
            values = [raw_answer]
        else:
            values = []
        values = sorted([str(v).strip().upper() for v in values if str(v).strip()])
        return ",".join(values)
    return str(raw_answer).strip()


def check_answer(question: Question, user_answer: str) -> bool:
    if question.qtype == "blank":
        return question.correct_answer.strip().lower() == user_answer.strip().lower()
    if question.qtype == "multiple":
        correct = sorted(
            [x.strip().upper() for x in question.correct_answer.split(",") if x.strip()]
        )
        got = sorted([x.strip().upper() for x in user_answer.split(",") if x.strip()])
        return correct == got
    return question.correct_answer.strip().upper() == user_answer.strip().upper()


def admin_required():
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("仅管理员可访问。", "error")
        return False
    return True


@app.route("/")
def index():
    categories = Category.query.order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return render_template("index.html", categories=categories)


@app.route("/register", methods=["GET", "POST"])
def register():
    flash("当前已关闭用户自注册，请联系管理员创建账号。", "error")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("用户名或密码错误。", "error")
            return redirect(url_for("login"))
        login_user(user)
        flash("登录成功。", "success")
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("已退出登录。", "success")
    return redirect(url_for("index"))


@app.route("/practice")
@login_required
def practice_categories():
    categories = Category.query.order_by(Category.sort_order.asc(), Category.id.asc()).all()
    category_ids = [c.id for c in categories]

    totals = {}
    if category_ids:
        totals_rows = (
            db.session.query(Question.category_id, func.count(Question.id))
            .filter(Question.category_id.in_(category_ids))
            .group_by(Question.category_id)
            .all()
        )
        totals = {cid: total for cid, total in totals_rows}

    done = {}
    if category_ids:
        done_rows = (
            db.session.query(Question.category_id, func.count(UserQuestionStatus.id))
            .join(UserQuestionStatus, UserQuestionStatus.question_id == Question.id)
            .filter(UserQuestionStatus.user_id == current_user.id)
            .filter(UserQuestionStatus.answered.is_(True))
            .filter(Question.category_id.in_(category_ids))
            .group_by(Question.category_id)
            .all()
        )
        done = {cid: cnt for cid, cnt in done_rows}

    progress = {}
    for c in categories:
        total = totals.get(c.id, 0)
        progress[c.id] = {"done": done.get(c.id, 0), "total": total}

    return render_template("practice_categories.html", categories=categories, progress=progress)


@app.route("/practice/<int:category_id>")
@login_required
def practice_question(category_id):
    category = db.session.get(Category, category_id)
    if not category:
        flash("题库不存在。", "error")
        return redirect(url_for("practice_categories"))
    questions = Question.query.filter_by(category_id=category_id).order_by(Question.id.asc()).all()
    if not questions:
        flash("该题库还没有题目。", "error")
        return redirect(url_for("practice_categories"))

    progress = PracticeProgress.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if not progress:
        progress = PracticeProgress(user_id=current_user.id, category_id=category_id, current_index=0)
        db.session.add(progress)
        db.session.commit()
    if progress.current_index >= len(questions):
        progress.current_index = len(questions) - 1
        db.session.commit()

    jump = request.args.get("q", "").strip()
    if jump.isdigit():
        idx = int(jump) - 1
        if 0 <= idx < len(questions):
            progress.current_index = idx
            db.session.commit()

    question = questions[progress.current_index]
    status = UserQuestionStatus.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()
    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question.id).first()
    statuses = {
        s.question_id: s
        for s in UserQuestionStatus.query.filter_by(user_id=current_user.id)
        .filter(UserQuestionStatus.question_id.in_([q.id for q in questions]))
        .all()
    }
    return render_template(
        "practice_question.html",
        category=category,
        question=question,
        questions=questions,
        statuses=statuses,
        current_index=progress.current_index + 1,
        total=len(questions),
        status=status,
        wrong=wrong,
    )


@app.post("/practice/<int:category_id>/submit")
@login_required
def submit_practice(category_id):
    question_id = int(request.form.get("question_id"))
    question = db.session.get(Question, question_id)
    if not question or question.category_id != category_id:
        flash("题目无效。", "error")
        return redirect(url_for("practice_question", category_id=category_id))

    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)

    status = UserQuestionStatus.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()
    if not status:
        status = UserQuestionStatus(user_id=current_user.id, question_id=question.id)
        db.session.add(status)
    status.answered = True
    status.is_correct = is_correct
    status.answer = answer
    status.last_answered_at = datetime.utcnow()

    if not is_correct:
        wrong = WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question.id
        ).first()
        if not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question.id))

    db.session.commit()
    flash("回答正确！" if is_correct else "回答错误，已可加入错题库。", "success" if is_correct else "error")
    return redirect(url_for("practice_question", category_id=category_id))


@app.post("/practice/<int:category_id>/next")
@login_required
def next_practice(category_id):
    questions_count = Question.query.filter_by(category_id=category_id).count()
    progress = PracticeProgress.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if not progress:
        progress = PracticeProgress(user_id=current_user.id, category_id=category_id, current_index=0)
        db.session.add(progress)
    else:
        progress.current_index = min(progress.current_index + 1, max(questions_count - 1, 0))
    db.session.commit()
    return redirect(url_for("practice_question", category_id=category_id))


@app.post("/practice/<int:category_id>/prev")
@login_required
def prev_practice(category_id):
    progress = PracticeProgress.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if progress:
        progress.current_index = max(progress.current_index - 1, 0)
        db.session.commit()
    return redirect(url_for("practice_question", category_id=category_id))


@app.post("/practice/<int:category_id>/goto")
@login_required
def goto_practice(category_id):
    target = request.form.get("target", "").strip()
    if not target.isdigit():
        return redirect(url_for("practice_question", category_id=category_id))
    questions_count = Question.query.filter_by(category_id=category_id).count()
    if questions_count <= 0:
        return redirect(url_for("practice_categories"))
    idx = max(0, min(int(target) - 1, questions_count - 1))
    progress = PracticeProgress.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if not progress:
        progress = PracticeProgress(user_id=current_user.id, category_id=category_id, current_index=idx)
        db.session.add(progress)
    else:
        progress.current_index = idx
    db.session.commit()
    return redirect(url_for("practice_question", category_id=category_id))


@app.post("/wrong/add/<int:question_id>")
@login_required
def wrong_add(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("index"))
    if not WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question_id).first():
        db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))
        db.session.commit()
    flash("已加入错题库。", "success")
    return redirect(request.referrer or url_for("wrong_list"))


@app.post("/wrong/remove/<int:question_id>")
@login_required
def wrong_remove(question_id):
    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if wrong:
        db.session.delete(wrong)
        db.session.commit()
    flash("已从错题库移除。", "success")
    return redirect(request.referrer or url_for("wrong_list"))


@app.route("/wrong")
@login_required
def wrong_list():
    wrongs = (
        db.session.query(WrongQuestion, Question, Category)
        .join(Question, WrongQuestion.question_id == Question.id)
        .join(Category, Question.category_id == Category.id)
        .filter(WrongQuestion.user_id == current_user.id)
        .order_by(WrongQuestion.created_at.desc())
        .all()
    )
    return render_template("wrong_list.html", wrongs=wrongs)


@app.get("/wrong/practice/start")
@login_required
def wrong_practice_start():
    wrongs = (
        WrongQuestion.query.filter_by(user_id=current_user.id)
        .order_by(WrongQuestion.created_at.desc())
        .all()
    )
    if not wrongs:
        flash("错题库为空。", "error")
        return redirect(url_for("wrong_list"))

    session = WrongPracticeSession(
        user_id=current_user.id, total_count=len(wrongs), current_index=0
    )
    db.session.add(session)
    db.session.flush()
    for idx, w in enumerate(wrongs):
        db.session.add(
            WrongPracticeQuestion(
                session_id=session.id, question_id=w.question_id, order_index=idx
            )
        )
    db.session.commit()
    return redirect(url_for("wrong_practice_question", session_id=session.id, index=1))


@app.route("/wrong/practice/<int:session_id>/<int:index>")
@login_required
def wrong_practice_question(session_id, index):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong_list"))
    if session.status != "in_progress":
        return redirect(url_for("wrong_practice_finish", session_id=session.id))

    total = session.total_count
    if index < 1 or index > total:
        return redirect(url_for("wrong_practice_question", session_id=session_id, index=1))

    if session.current_index != index - 1:
        session.current_index = index - 1
        db.session.commit()

    items = (
        WrongPracticeQuestion.query.filter_by(session_id=session_id)
        .order_by(WrongPracticeQuestion.order_index.asc())
        .all()
    )
    question_ids = [it.question_id for it in items]
    question_map = {it.order_index: it for it in items}
    eq = question_map.get(index - 1)
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("wrong_practice_question", session_id=session_id, index=1))

    questions = [it.question for it in items]

    statuses = (
        UserQuestionStatus.query.filter_by(user_id=current_user.id)
        .filter(UserQuestionStatus.question_id.in_(question_ids))
        .all()
    )
    status_map = {s.question_id: s for s in statuses}

    wrong_qs = WrongQuestion.query.filter_by(user_id=current_user.id).filter(
        WrongQuestion.question_id.in_(question_ids)
    ).all()
    wrong_map = {w.question_id: w for w in wrong_qs}

    status = status_map.get(eq.question_id)
    wrong = wrong_map.get(eq.question_id)
    return render_template(
        "wrong_practice_question.html",
        session=session,
        question=eq.question,
        questions=questions,
        statuses=status_map,
        status=status,
        wrong=wrong,
        current_index=session.current_index + 1,
        total=total,
        index=index,
    )


@app.post("/wrong/practice/<int:session_id>/goto")
@login_required
def wrong_practice_goto(session_id):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong_list"))
    if session.status != "in_progress":
        return redirect(url_for("wrong_practice_finish", session_id=session.id))

    target = request.form.get("target", "").strip()
    if not target.isdigit():
        return redirect(url_for("wrong_practice_question", session_id=session_id, index=1))
    idx = int(target) - 1
    idx = max(0, min(idx, session.total_count - 1))
    session.current_index = idx
    db.session.commit()
    return redirect(url_for("wrong_practice_question", session_id=session_id, index=idx + 1))


@app.post("/wrong/practice/<int:session_id>/<int:index>/submit")
@login_required
def wrong_practice_submit(session_id, index):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id or session.status != "in_progress":
        flash("练习状态无效。", "error")
        return redirect(url_for("wrong_list"))

    eq = WrongPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("wrong_practice_question", session_id=session_id, index=1))

    question = eq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)

    eq.user_answer = answer
    eq.is_correct = is_correct

    status = UserQuestionStatus.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()
    if not status:
        status = UserQuestionStatus(user_id=current_user.id, question_id=question.id)
        db.session.add(status)
    status.answered = True
    status.is_correct = is_correct
    status.answer = answer
    status.last_answered_at = datetime.utcnow()

    wrong = WrongQuestion.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()

    if is_correct:
        # 错题练习：做对就从错题库移除
        if wrong:
            db.session.delete(wrong)
    else:
        if not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question.id))

    db.session.commit()

    if index >= session.total_count:
        session.status = "finished"
        db.session.commit()
        return redirect(url_for("wrong_practice_finish", session_id=session.id))

    session.current_index = index  # 下一题的 0-based
    db.session.commit()
    return redirect(url_for("wrong_practice_question", session_id=session.id, index=index + 1))


@app.route("/wrong/practice/<int:session_id>/finish")
@login_required
def wrong_practice_finish(session_id):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong_list"))

    correct_count = (
        WrongPracticeQuestion.query.filter_by(session_id=session.id, is_correct=True).count()
    )
    return render_template(
        "wrong_practice_finish.html",
        session=session,
        correct_count=correct_count,
    )


@app.route("/exam/start", methods=["GET", "POST"])
@login_required
def exam_start():
    if request.method == "POST":
        count = int(request.form.get("count", "10"))
        all_questions = Question.query.all()
        if not all_questions:
            flash("暂无题目，无法开始考试。", "error")
            return redirect(url_for("exam_start"))

        count = max(1, min(count, len(all_questions)))
        picked = random.sample(all_questions, count)

        # scope=all 代表从所有题库抽题；category_id 只是为了满足外键约束并用于兼容旧数据
        first_category = Category.query.order_by(Category.sort_order.asc(), Category.id.asc()).first()
        if not first_category:
            flash("暂无题库大类，无法开始考试。", "error")
            return redirect(url_for("exam_start"))

        session = ExamSession(
            user_id=current_user.id,
            category_id=first_category.id,
            total_count=count,
            scope="all",
        )
        db.session.add(session)
        db.session.flush()
        for idx, q in enumerate(picked):
            db.session.add(ExamQuestion(session_id=session.id, question_id=q.id, order_index=idx))
        db.session.commit()
        return redirect(url_for("exam_question", session_id=session.id, index=1))

    return render_template("exam_start.html")


@app.route("/exam/<int:session_id>/<int:index>")
@login_required
def exam_question(session_id, index):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("考试不存在。", "error")
        return redirect(url_for("exam_start"))
    if session.status != "in_progress":
        return redirect(url_for("exam_result", session_id=session.id))
    if index < 1 or index > session.total_count:
        return redirect(url_for("exam_question", session_id=session_id, index=1))
    eq = ExamQuestion.query.filter_by(session_id=session_id, order_index=index - 1).first()
    return render_template(
        "exam_question.html",
        session=session,
        eq=eq,
        index=index,
        total=session.total_count,
    )


@app.post("/exam/<int:session_id>/<int:index>/submit")
@login_required
def exam_submit(session_id, index):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id or session.status != "in_progress":
        flash("考试状态无效。", "error")
        return redirect(url_for("exam_start"))
    eq = ExamQuestion.query.filter_by(session_id=session_id, order_index=index - 1).first()
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("exam_question", session_id=session_id, index=1))

    question = eq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    answer = normalize_answer(question.qtype, raw)
    eq.user_answer = answer
    eq.is_correct = check_answer(question, answer)
    db.session.commit()

    if index >= session.total_count:
        return redirect(url_for("exam_finish", session_id=session_id))
    return redirect(url_for("exam_question", session_id=session_id, index=index + 1))


@app.route("/exam/<int:session_id>/finish")
@login_required
def exam_finish(session_id):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("考试不存在。", "error")
        return redirect(url_for("exam_start"))
    if session.status == "finished":
        return redirect(url_for("exam_result", session_id=session.id))

    correct = ExamQuestion.query.filter_by(session_id=session.id, is_correct=True).count()
    session.correct_count = correct
    session.score = round(correct * 100.0 / session.total_count, 2)
    session.passed = session.score >= 60
    session.status = "finished"
    db.session.commit()
    return redirect(url_for("exam_result", session_id=session.id))


@app.route("/exam/<int:session_id>/result")
@login_required
def exam_result(session_id):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("考试不存在。", "error")
        return redirect(url_for("exam_start"))
    questions = (
        ExamQuestion.query.filter_by(session_id=session.id)
        .order_by(ExamQuestion.order_index.asc())
        .all()
    )
    return render_template("exam_result.html", session=session, questions=questions)


@app.route("/admin")
@login_required
def admin_home():
    if not admin_required():
        return redirect(url_for("index"))
    categories = Category.query.order_by(Category.sort_order.asc(), Category.id.asc()).all()
    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin_home.html", categories=categories, users=users)


@app.route("/admin/users")
@login_required
def admin_users():
    if not admin_required():
        return redirect(url_for("index"))
    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin_users.html", users=users)


@app.post("/admin/category/add")
@login_required
def admin_category_add():
    if not admin_required():
        return redirect(url_for("index"))
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    sort_order_raw = request.form.get("sort_order", "0").strip()
    sort_order = int(sort_order_raw) if sort_order_raw.lstrip("-").isdigit() else 0
    if not name:
        flash("分类名不能为空。", "error")
        return redirect(url_for("admin_home"))
    if Category.query.filter_by(name=name).first():
        flash("分类已存在。", "error")
        return redirect(url_for("admin_home"))
    db.session.add(Category(name=name, description=desc, sort_order=sort_order))
    db.session.commit()
    flash("分类已创建。", "success")
    return redirect(url_for("admin_home"))


@app.post("/admin/category/edit/<int:category_id>")
@login_required
def admin_category_edit(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin_home"))
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    sort_order_raw = request.form.get("sort_order", "0").strip()
    sort_order = int(sort_order_raw) if sort_order_raw.lstrip("-").isdigit() else 0
    if not name:
        flash("分类名不能为空。", "error")
        return redirect(url_for("admin_home"))
    conflict = Category.query.filter(Category.name == name, Category.id != category_id).first()
    if conflict:
        flash("分类名已存在。", "error")
        return redirect(url_for("admin_home"))
    category.name = name
    category.description = desc
    category.sort_order = sort_order
    db.session.commit()
    flash("分类已更新。", "success")
    return redirect(url_for("admin_home"))


@app.post("/admin/category/delete/<int:category_id>")
@login_required
def admin_category_delete(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin_home"))
    if Question.query.filter_by(category_id=category_id).count() > 0:
        flash("该分类下有题目，不能删除。", "error")
        return redirect(url_for("admin_home"))
    db.session.delete(category)
    db.session.commit()
    flash("分类已删除。", "success")
    return redirect(url_for("admin_home"))


@app.route("/admin/questions/<int:category_id>")
@login_required
def admin_questions(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin_home"))
    questions = Question.query.filter_by(category_id=category_id).order_by(Question.id.asc()).all()
    return render_template("admin_questions.html", category=category, questions=questions)


@app.route("/admin/question/edit/<int:question_id>", methods=["GET", "POST"])
@login_required
def admin_question_edit(question_id):
    if not admin_required():
        return redirect(url_for("index"))
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("admin_home"))
    if request.method == "POST":
        qtype = request.form.get("qtype", "").strip()
        stem = request.form.get("stem", "").strip()
        answer = request.form.get("answer", "").strip()
        explanation = request.form.get("explanation", "").strip()
        if qtype not in ("single", "multiple", "blank") or not stem or not answer:
            flash("请完整填写题型、题干、答案。", "error")
            return redirect(url_for("admin_question_edit", question_id=question_id))

        question.qtype = qtype
        question.stem = stem
        question.correct_answer = answer
        question.explanation = explanation

        if qtype in ("single", "multiple"):
            option_keys = request.form.getlist("option_key")
            option_values = request.form.getlist("option_text")
            Choice.query.filter_by(question_id=question.id).delete()
            for key, value in zip(option_keys, option_values):
                k = key.strip().upper()
                v = value.strip()
                if k and v:
                    db.session.add(Choice(question_id=question.id, option_key=k, option_text=v))
        else:
            Choice.query.filter_by(question_id=question.id).delete()

        db.session.commit()
        flash("题目已更新。", "success")
        return redirect(url_for("admin_questions", category_id=question.category_id))

    choices = Choice.query.filter_by(question_id=question.id).order_by(Choice.option_key.asc()).all()
    return render_template("admin_question_edit.html", question=question, choices=choices)


@app.post("/admin/question/delete/<int:question_id>")
@login_required
def admin_question_delete(question_id):
    if not admin_required():
        return redirect(url_for("index"))
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("admin_home"))
    category_id = question.category_id
    Choice.query.filter_by(question_id=question.id).delete()
    UserQuestionStatus.query.filter_by(question_id=question.id).delete()
    WrongQuestion.query.filter_by(question_id=question.id).delete()
    db.session.delete(question)
    db.session.commit()
    flash("题目已删除。", "success")
    return redirect(url_for("admin_questions", category_id=category_id))


@app.route("/admin/import/<int:category_id>", methods=["GET", "POST"])
@login_required
def admin_import_questions(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin_home"))

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content:
            flash("导入内容不能为空。", "error")
            return redirect(url_for("admin_import_questions", category_id=category_id))
        try:
            data = json.loads(content)
            imported = 0
            for row in data:
                qtype = row.get("qtype", "").strip()
                stem = row.get("stem", "").strip()
                answer = str(row.get("answer", "")).strip()
                explanation = str(row.get("explanation", "")).strip()
                options = row.get("options", {})
                if qtype not in ("single", "multiple", "blank") or not stem or not answer:
                    continue
                q = Question(
                    category_id=category_id,
                    qtype=qtype,
                    stem=stem,
                    correct_answer=answer,
                    explanation=explanation,
                )
                db.session.add(q)
                db.session.flush()
                if qtype in ("single", "multiple"):
                    for key, value in options.items():
                        db.session.add(
                            Choice(question_id=q.id, option_key=str(key).upper(), option_text=str(value))
                        )
                imported += 1
            db.session.commit()
            flash(f"导入完成，新增 {imported} 道题。", "success")
            return redirect(url_for("admin_home"))
        except Exception as ex:
            flash(f"导入失败: {ex}", "error")
            return redirect(url_for("admin_import_questions", category_id=category_id))

    sample = """[
  {
    "qtype": "single",
    "stem": "Python 中用于定义函数的关键字是？",
    "options": {"A": "func", "B": "def", "C": "lambda"},
    "answer": "B",
    "explanation": "def 用于定义函数。"
  },
  {
    "qtype": "multiple",
    "stem": "以下哪些是 Python 基本数据类型？",
    "options": {"A": "list", "B": "dict", "C": "table"},
    "answer": "A,B",
    "explanation": "list 和 dict 都是基础类型。"
  },
  {
    "qtype": "blank",
    "stem": "Python 之父是 ____。",
    "answer": "Guido van Rossum",
    "explanation": "这是常识题。"
  }
]"""
    return render_template("admin_import.html", category=category, sample=sample)


@app.post("/admin/user/toggle_admin/<int:user_id>")
@login_required
def admin_toggle_user(user_id):
    if not admin_required():
        return redirect(url_for("index"))
    user = db.session.get(User, user_id)
    if not user:
        flash("用户不存在。", "error")
        return redirect(url_for("admin_home"))
    if user.id == current_user.id:
        flash("不能修改自己管理员状态。", "error")
        return redirect(url_for("admin_home"))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"已更新用户 {user.username} 管理员状态。", "success")
    return redirect(url_for("admin_home"))


@app.post("/admin/user/add")
@login_required
def admin_user_add():
    if not admin_required():
        return redirect(url_for("index"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    is_admin = request.form.get("is_admin") == "on"
    if not username or not password:
        flash("用户名和密码不能为空。", "error")
        return redirect(url_for("admin_home"))
    if User.query.filter_by(username=username).first():
        flash("用户名已存在。", "error")
        return redirect(url_for("admin_home"))
    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"用户 {username} 已创建。", "success")
    return redirect(url_for("admin_home"))


def init_db():
    with app.app_context():
        db.create_all()
        # SQLite 不会自动做列级迁移；这里做最小化补齐，保证老数据库也能跑。
        inspector = sqlalchemy_inspect(db.engine)

        category_columns = [col["name"] for col in inspector.get_columns("category")]
        if "sort_order" not in category_columns:
            db.session.execute(
                sql_text(
                    "ALTER TABLE category ADD COLUMN sort_order INTEGER DEFAULT 0"
                )
            )
            db.session.commit()

        exam_session_columns = [col["name"] for col in inspector.get_columns("exam_session")]
        if "scope" not in exam_session_columns:
            db.session.execute(
                sql_text("ALTER TABLE exam_session ADD COLUMN scope VARCHAR(20) DEFAULT 'category'")
            )
            db.session.commit()
        
        # 检查并添加 ai_explanation 字段
        question_columns = [col["name"] for col in inspector.get_columns("question")]
        if "ai_explanation" not in question_columns:
            db.session.execute(
                sql_text("ALTER TABLE question ADD COLUMN ai_explanation TEXT")
            )
            db.session.commit()
        
        if not User.query.filter_by(username="admin").first():
            admin = User(username="admin", is_admin=True)
            admin.set_password("admin123")
            db.session.add(admin)
            db.session.commit()


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
