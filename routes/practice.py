from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
from models import db, Category, Question, Choice, PracticeProgress, WrongQuestion
from utils import normalize_answer, check_answer, _now_shanghai

practice_bp = Blueprint('practice', __name__)


@practice_bp.route("/practice")
@login_required
def practice_categories():
    # 只获取启用的分类
    categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order.asc(), Category.name.asc()).all()
    
    # 获取每个分类的进度统计
    progress = {}
    practice_stats = {}
    
    for cat in categories:
        total = Question.query.filter_by(category_id=cat.id).count()
        answered = PracticeProgress.query.filter_by(user_id=current_user.id).join(
            Question, PracticeProgress.question_id == Question.id
        ).filter(Question.category_id == cat.id).count()
        correct = PracticeProgress.query.filter_by(
            user_id=current_user.id, is_correct=True
        ).join(
            Question, PracticeProgress.question_id == Question.id
        ).filter(Question.category_id == cat.id).count()
        
        wrong_count = PracticeProgress.query.filter_by(
            user_id=current_user.id, is_correct=False
        ).join(
            Question, PracticeProgress.question_id == Question.id
        ).filter(Question.category_id == cat.id).count()
        
        unanswered = total - answered
        
        progress[cat.id] = {
            'total': total,
            'answered': answered,
            'correct': correct,
            'wrong': wrong_count,
            'unanswered': unanswered
        }
        
        practice_stats[cat.id] = {
            'total': total,
            'correct': correct,
            'wrong': wrong_count,
            'unanswered': unanswered,
            'empty_submit': 0,  # 填空题未作答数
            'pending': 0  # 待确认数（填空题自评）
        }
    
    return render_template(
        "practice_categories.html", 
        categories=categories, 
        progress=progress,
        practice_stats=practice_stats
    )


@practice_bp.route("/practice/<int:category_id>")
@login_required
def practice_question(category_id):
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("practice.practice_categories"))
    
    questions = Question.query.filter_by(category_id=category_id).all()
    if not questions:
        flash("该分类下暂无题目。", "info")
        return redirect(url_for("practice.practice_categories"))
    
    progress = {
        p.question_id: p 
        for p in PracticeProgress.query.filter_by(user_id=current_user.id).all()
    }
    
    # 计算练习统计
    total = len(questions)
    correct = sum(1 for q in questions if q.id in progress and progress[q.id].is_correct == True)
    wrong = sum(1 for q in questions if q.id in progress and progress[q.id].is_correct == False)
    answered = sum(1 for q in questions if q.id in progress and progress[q.id].answered)
    unanswered = total - answered
    
    # 统计填空题相关数据
    blank_questions = [q for q in questions if q.qtype == 'blank']
    empty_submit = sum(1 for q in blank_questions if q.id in progress and progress[q.id].answer == '')
    pending = sum(1 for q in blank_questions if q.id in progress and progress[q.id].is_correct is None)
    
    practice_stats = {
        'total': total,
        'correct': correct,
        'wrong': wrong,
        'unanswered': unanswered,
        'empty_submit': empty_submit,
        'pending': pending
    }
    
    return render_template(
        "practice_question.html",
        category=category,
        questions=questions,
        progress=progress,
        practice_stats=practice_stats
    )


@practice_bp.route("/practice/<int:category_id>/submit", methods=["POST"])
@login_required
def practice_submit(category_id):
    question_id = request.form.get("question_id", type=int)
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("practice.practice_question", category_id=category_id))
    
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    
    answer = normalize_answer(question.qtype, raw)
    is_correct = check_answer(question, answer)
    
    status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if not status:
        status = PracticeProgress(user_id=current_user.id, question_id=question_id)
        db.session.add(status)
    
    status.answered = True
    status.is_correct = is_correct
    status.answer = answer
    status.last_answered_at = _now_shanghai()
    
    wrong = WrongQuestion.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if is_correct:
        if wrong:
            db.session.delete(wrong)
    else:
        if not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))
    
    db.session.commit()
    
    flash("回答正确！" if is_correct else "回答错误，已加入错题库。", 
          "success" if is_correct else "error")
    
    return redirect(url_for("practice.practice_question", category_id=category_id))


@practice_bp.route("/practice/<int:category_id>/goto", methods=["POST"])
@login_required
def goto_practice(category_id):
    """跳转到指定题目"""
    target = request.form.get("target", "").strip()
    if not target.isdigit():
        return redirect(url_for("practice.practice_question", category_id=category_id))
    
    idx = int(target)
    questions = Question.query.filter_by(category_id=category_id).all()
    
    if idx < 1 or idx > len(questions):
        idx = 1
    
    flash(f"已跳转到第 {idx} 题", "info")
    return redirect(url_for("practice.practice_question", category_id=category_id))


@practice_bp.route("/practice/<int:category_id>/next", methods=["POST"])
@login_required
def next_practice(category_id):
    """下一题"""
    question_id = request.form.get("question_id", type=int)
    questions = Question.query.filter_by(category_id=category_id).order_by(Question.id.asc()).all()
    
    current_idx = None
    for i, q in enumerate(questions):
        if q.id == question_id:
            current_idx = i
            break
    
    if current_idx is not None and current_idx < len(questions) - 1:
        next_q = questions[current_idx + 1]
        return redirect(url_for("practice.practice_question", category_id=category_id))
    
    flash("已经是最后一题了", "info")
    return redirect(url_for("practice.practice_question", category_id=category_id))


@practice_bp.route("/practice/<int:category_id>/prev", methods=["POST"])
@login_required
def prev_practice(category_id):
    """上一题"""
    question_id = request.form.get("question_id", type=int)
    questions = Question.query.filter_by(category_id=category_id).order_by(Question.id.asc()).all()
    
    current_idx = None
    for i, q in enumerate(questions):
        if q.id == question_id:
            current_idx = i
            break
    
    if current_idx is not None and current_idx > 0:
        prev_q = questions[current_idx - 1]
        return redirect(url_for("practice.practice_question", category_id=category_id))
    
    flash("已经是第一题了", "info")
    return redirect(url_for("practice.practice_question", category_id=category_id))


@practice_bp.route("/practice/mark-mastered/<int:question_id>", methods=["POST"])
@login_required
def mark_mastered(question_id):
    """标记填空题为已掌握"""
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("index"))
    
    status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if status:
        status.is_correct = True
        
        wrong = WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question_id
        ).first()
        if wrong:
            db.session.delete(wrong)
        
        db.session.commit()
        flash("已标记为已掌握", "success")
    
    referrer = request.referrer or ""
    return redirect(referrer or url_for("practice.practice_question", category_id=question.category_id))


@practice_bp.route("/practice/mark-wrong/<int:question_id>", methods=["POST"])
@login_required
def mark_wrong(question_id):
    """标记填空题为错误"""
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("index"))
    
    status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if status:
        status.is_correct = False
        
        wrong = WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question_id
        ).first()
        if not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))
        
        db.session.commit()
        flash("已标记为错误并加入错题库", "info")
    
    referrer = request.referrer or ""
    return redirect(referrer or url_for("practice.practice_question", category_id=question.category_id))


@practice_bp.route("/practice/category-stats/<int:category_id>")
@login_required
def practice_category_stats(category_id):
    """获取分类统计信息（AJAX）"""
    from flask import jsonify
    
    category = db.session.get(Category, category_id)
    if not category:
        return jsonify({"error": "分类不存在"}), 404
    
    total = Question.query.filter_by(category_id=category_id).count()
    answered = PracticeProgress.query.filter_by(
        user_id=current_user.id
    ).join(Question).filter(Question.category_id == category_id).count()
    correct = PracticeProgress.query.filter_by(
        user_id=current_user.id, is_correct=True
    ).join(Question).filter(Question.category_id == category_id).count()
    
    return jsonify({
        "total": total,
        "answered": answered,
        "correct": correct,
        "wrong": answered - correct,
        "unanswered": total - answered
    })