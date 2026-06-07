from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
import random
from models import db, Category, Question, ExamSession, ExamQuestion
from utils import normalize_answer, check_answer

exam_bp = Blueprint('exam', __name__)


@exam_bp.route("/exam/start", methods=["GET", "POST"])
@login_required
def exam_start():
    if request.method == "POST":
        category_id = request.form.get("category_id", type=int)
        count = int(request.form.get("count", "10"))
        scope = request.form.get("scope", "category")
        
        category = db.session.get(Category, category_id)
        if not category:
            flash("分类不存在。", "error")
            return redirect(url_for("exam.exam_start"))
        
        if scope == "all":
            questions = Question.query.all()
        else:
            questions = Question.query.filter_by(category_id=category_id).all()
        
        if len(questions) < count:
            flash(f"题目数量不足，仅有 {len(questions)} 道题。", "warning")
            count = len(questions)
        
        if count == 0:
            flash("暂无可考试的题目。", "error")
            return redirect(url_for("exam.exam_start"))
        
        picked = random.sample(questions, count)
        
        session = ExamSession(
            user_id=current_user.id,
            category_id=category_id,
            total_count=count,
            scope=scope
        )
        db.session.add(session)
        db.session.flush()
        
        for idx, q in enumerate(picked):
            db.session.add(
                ExamQuestion(
                    session_id=session.id,
                    question_id=q.id,
                    order_index=idx
                )
            )
        
        db.session.commit()
        return redirect(url_for("exam.exam_question", session_id=session.id, index=1))
    
    categories = Category.query.order_by(Category.sort_order.asc(), Category.name.asc()).all()
    return render_template("exam_start.html", categories=categories)


@exam_bp.route("/exam/<int:session_id>/<int:index>")
@login_required
def exam_question(session_id, index):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("考试不存在。", "error")
        return redirect(url_for("exam.exam_start"))
    
    if session.status != "in_progress":
        return redirect(url_for("exam.exam_result", session_id=session.id))
    
    total = session.total_count
    if index < 1 or index > total:
        return redirect(url_for("exam.exam_question", session_id=session_id, index=1))
    
    eq = ExamQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("exam.exam_question", session_id=session_id, index=1))
    
    return render_template(
        "exam_question.html",
        session=session,
        question=eq.question,
        current_index=index,
        total=total,
        index=index
    )


@exam_bp.route("/exam/<int:session_id>/<int:index>/submit", methods=["POST"])
@login_required
def exam_submit(session_id, index):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id or session.status != "in_progress":
        flash("考试状态无效。", "error")
        return redirect(url_for("exam.exam_start"))
    
    eq = ExamQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("exam.exam_question", session_id=session_id, index=1))
    
    question = eq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)
    
    eq.user_answer = answer
    eq.is_correct = is_correct
    
    db.session.commit()
    
    next_index = index + 1
    if next_index > session.total_count:
        session.status = "finished"
        correct_count = ExamQuestion.query.filter_by(
            session_id=session.id, is_correct=True
        ).count()
        session.correct_count = correct_count
        session.score = (correct_count / session.total_count) * 100
        session.passed = session.score >= 60
        db.session.commit()
        return redirect(url_for("exam.exam_result", session_id=session.id))
    
    return redirect(url_for("exam.exam_question", session_id=session.id, index=next_index))


@exam_bp.route("/exam/<int:session_id>/result")
@login_required
def exam_result(session_id):
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("考试不存在。", "error")
        return redirect(url_for("exam.exam_start"))
    
    questions = ExamQuestion.query.filter_by(session_id=session.id).order_by(
        ExamQuestion.order_index.asc()
    ).all()
    
    return render_template("exam_result.html", session=session, questions=questions)