from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from models import db, WrongQuestion, Question, WrongPracticeSession, WrongPracticeQuestion, PracticeProgress
from utils import normalize_answer, check_answer, _now_shanghai

wrong_bp = Blueprint('wrong', __name__)


@wrong_bp.route("/wrong")
@login_required
def wrong_list():
    wrongs = WrongQuestion.query.filter_by(user_id=current_user.id).all()
    questions = [w.question for w in wrongs if w.question]
    return render_template("wrong_list.html", questions=questions)


@wrong_bp.route("/wrong/practice/start", methods=["POST"])
@login_required
def wrong_practice_start():
    wrongs = WrongQuestion.query.filter_by(user_id=current_user.id).all()
    if not wrongs:
        flash("暂无错题。", "info")
        return redirect(url_for("wrong.wrong_list"))
    
    question_ids = [w.question_id for w in wrongs]
    
    session = WrongPracticeSession(
        user_id=current_user.id,
        total_count=len(question_ids),
        current_index=0
    )
    db.session.add(session)
    db.session.flush()
    
    for idx, qid in enumerate(question_ids):
        db.session.add(
            WrongPracticeQuestion(
                session_id=session.id,
                question_id=qid,
                order_index=idx
            )
        )
    
    db.session.commit()
    return redirect(url_for("wrong.wrong_practice_question", session_id=session.id, index=1))


@wrong_bp.route("/wrong/practice/<int:session_id>/<int:index>")
@login_required
def wrong_practice_question(session_id, index):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong.wrong_list"))
    
    if session.status != "in_progress":
        return redirect(url_for("wrong.wrong_practice_finish", session_id=session.id))
    
    total = session.total_count
    if index < 1 or index > total:
        return redirect(url_for("wrong.wrong_practice_question", session_id=session_id, index=1))
    
    if session.current_index != index - 1:
        session.current_index = index - 1
        db.session.commit()
    
    eq = WrongPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("wrong.wrong_practice_question", session_id=session_id, index=1))
    
    items = WrongPracticeQuestion.query.filter_by(session_id=session_id).order_by(
        WrongPracticeQuestion.order_index.asc()
    ).all()
    
    return render_template(
        "wrong_practice_question.html",
        session=session,
        question=eq.question,
        questions=[it.question for it in items],
        statuses={it.question_id: it for it in items},
        status=eq if eq.user_answer else None,
        current_index=session.current_index + 1,
        total=total,
        index=index
    )


@wrong_bp.route("/wrong/practice/<int:session_id>/<int:index>/submit", methods=["POST"])
@login_required
def wrong_practice_submit(session_id, index):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id or session.status != "in_progress":
        flash("练习状态无效。", "error")
        return redirect(url_for("wrong.wrong_list"))
    
    eq = WrongPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("wrong.wrong_practice_question", session_id=session_id, index=1))
    
    question = eq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)
    
    eq.user_answer = answer
    eq.is_correct = is_correct
    
    if is_correct:
        wrong = WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question.id
        ).first()
        if wrong:
            db.session.delete(wrong)
        flash("回答正确！已从错题库移除。", "success")
    else:
        flash("回答错误，仍在错题库中。", "error")
    
    db.session.commit()
    return redirect(url_for("wrong.wrong_practice_question", session_id=session.id, index=index))


@wrong_bp.route("/wrong/practice/<int:session_id>/<int:index>/next", methods=["POST"])
@login_required
def wrong_practice_next(session_id, index):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong.wrong_list"))
    
    if session.status != "in_progress":
        return redirect(url_for("wrong.wrong_practice_finish", session_id=session.id))
    
    next_index = index + 1
    if next_index > session.total_count:
        session.status = "finished"
        db.session.commit()
        return redirect(url_for("wrong.wrong_practice_finish", session_id=session.id))
    
    session.current_index = next_index - 1
    db.session.commit()
    return redirect(url_for("wrong.wrong_practice_question", session_id=session.id, index=next_index))


@wrong_bp.route("/wrong/practice/<int:session_id>/finish")
@login_required
def wrong_practice_finish(session_id):
    session = db.session.get(WrongPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("wrong.wrong_list"))
    
    correct_count = WrongPracticeQuestion.query.filter_by(
        session_id=session.id, is_correct=True
    ).count()
    
    return render_template(
        "wrong_practice_finish.html",
        session=session,
        correct_count=correct_count
    )


@wrong_bp.route("/wrong/remove/<int:question_id>", methods=["POST"])
@login_required
def wrong_remove(question_id):
    """从错题库移除"""
    wrong = WrongQuestion.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if wrong:
        db.session.delete(wrong)
        db.session.commit()
        flash("已从错题库移除", "success")
    
    referrer = request.referrer or ""
    return redirect(referrer or url_for("wrong.wrong_list"))


@wrong_bp.route("/wrong/add/<int:question_id>", methods=["POST"])
@login_required
def wrong_add(question_id):
    """添加到错题库"""
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("index"))
    
    wrong = WrongQuestion.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if not wrong:
        db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))
        db.session.commit()
        flash("已加入错题库", "info")
    
    referrer = request.referrer or ""
    return redirect(referrer or url_for("wrong.wrong_list"))