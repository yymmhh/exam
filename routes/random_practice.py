from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, current_user
import random
from models import db, Category, Question, RandomPracticeSession, RandomPracticeQuestion
from utils import normalize_answer, check_answer

random_practice_bp = Blueprint('random_practice', __name__)


@random_practice_bp.route("/random-practice/start", methods=["GET", "POST"])
@login_required
def random_practice_start():
    # 只获取启用的分类
    all_categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order.asc(), Category.name.asc()).all()
    
    if request.method == "POST":
        category_ids_str = request.form.get("category_ids", "")
        if category_ids_str:
            category_ids = [int(cid) for cid in category_ids_str.split(",") if cid.strip()]
        else:
            category_ids = [c.id for c in all_categories]

        if not category_ids:
            flash("请至少选择一个题库。", "error")
            return redirect(url_for("random_practice.random_practice_start"))

        # 只从启用的分类中获取题目
        all_categories = Category.query.filter(Category.id.in_(category_ids), Category.is_active==True).all()
        if not all_categories:
            flash("选择的题库不可用。", "error")
            return redirect(url_for("random_practice.random_practice_start"))

        count = int(request.form.get("count", "10"))
        
        # 从选中的分类中获取所有题目
        questions = Question.query.filter(Question.category_id.in_(category_ids)).all()
        
        if len(questions) < count:
            flash(f"题目数量不足，仅有 {len(questions)} 道题。", "warning")
            count = len(questions)
        
        if count == 0:
            flash("暂无可练习的题目。", "error")
            return redirect(url_for("random_practice.random_practice_start"))
        
        picked = random.sample(questions, count)
        
        # 创建会话
        practice_session = RandomPracticeSession(
            user_id=current_user.id,
            total_count=count
        )
        db.session.add(practice_session)
        db.session.flush()
        
        for idx, q in enumerate(picked):
            db.session.add(
                RandomPracticeQuestion(
                    session_id=practice_session.id,
                    question_id=q.id,
                    order_index=idx
                )
            )
        
        db.session.commit()
        return redirect(url_for("random_practice.random_practice_question", session_id=practice_session.id, index=1))
    
    return render_template("random_practice_start.html", categories=all_categories)


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>")
@login_required
def random_practice_question(session_id, index):
    practice_session = db.session.get(RandomPracticeSession, session_id)
    if not practice_session or practice_session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    if practice_session.status != "in_progress":
        return redirect(url_for("random_practice.random_practice_finish", session_id=practice_session.id))
    
    total = practice_session.total_count
    if index < 1 or index > total:
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    pq = RandomPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not pq:
        flash("题目不存在。", "error")
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    return render_template(
        "random_practice_question.html",
        session=practice_session,
        question=pq.question,
        current_index=index,
        total=total,
        index=index,
        pq=pq
    )


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>/submit", methods=["POST"])
@login_required
def random_practice_submit(session_id, index):
    practice_session = db.session.get(RandomPracticeSession, session_id)
    if not practice_session or practice_session.user_id != current_user.id or practice_session.status != "in_progress":
        flash("练习状态无效。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    pq = RandomPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not pq:
        flash("题目不存在。", "error")
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    question = pq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)
    
    pq.user_answer = answer
    pq.is_correct = is_correct
    pq.has_submitted = True
    
    db.session.commit()
    
    next_index = index + 1
    if next_index > practice_session.total_count:
        practice_session.status = "finished"
        db.session.commit()
        return redirect(url_for("random_practice.random_practice_finish", session_id=practice_session.id))
    
    return redirect(url_for("random_practice.random_practice_question", session_id=practice_session.id, index=next_index))


@random_practice_bp.route("/random-practice/<int:session_id>/finish")
@login_required
def random_practice_finish(session_id):
    practice_session = db.session.get(RandomPracticeSession, session_id)
    if not practice_session or practice_session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    questions = RandomPracticeQuestion.query.filter_by(session_id=practice_session.id).order_by(
        RandomPracticeQuestion.order_index.asc()
    ).all()
    
    return render_template("random_practice_finish.html", session=practice_session, questions=questions)
