from flask import Blueprint, flash, redirect, render_template, request, url_for, jsonify
from flask_login import login_required, current_user
import random
from models import db, Category, Question, ExamSession, ExamQuestion, AnkiReviewLog, AnkiCard
from utils import normalize_answer, check_answer, _now_shanghai, render_markdown
from datetime import datetime

exam_bp = Blueprint('exam', __name__)


@exam_bp.route("/exam/start", methods=["GET", "POST"])
@login_required
def exam_start():
    if request.method == "POST":
        category_id_str = request.form.get("category_id", "").strip()
        category_id = int(category_id_str) if category_id_str else None
        count = int(request.form.get("count", "10"))
        
        # 如果选择了特定分类，验证分类是否存在且已启用
        if category_id:
            category = db.session.get(Category, category_id)
            if not category or not category.is_active:
                flash("分类不存在或已禁用。", "error")
                return redirect(url_for("exam.exam_start"))
        
        # 根据选择的范围获取题目（只从启用的分类中获取）
        if category_id:
            questions = Question.query.filter_by(category_id=category_id).all()
        else:
            # 获取所有启用分类的题目
            active_categories = Category.query.filter_by(is_active=True).all()
            active_category_ids = [c.id for c in active_categories]
            if active_category_ids:
                questions = Question.query.filter(Question.category_id.in_(active_category_ids)).all()
            else:
                questions = []
        
        if len(questions) < count:
            flash(f"题目数量不足，仅有 {len(questions)} 道题。", "warning")
            count = len(questions)
        
        if count == 0:
            flash("暂无可考试的题目。", "error")
            return redirect(url_for("exam.exam_start"))
        
        picked = random.sample(questions, count)
        
        session = ExamSession(
            user_id=current_user.id,
            category_id=category_id if category_id else 0,  # 0 表示全部题库
            total_count=count,
            scope="category" if category_id else "all"
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
    
    # 只获取启用的分类
    categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order.asc(), Category.name.asc()).all()
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
    
    # 获取题目被刷过的次数
    review_count = AnkiReviewLog.query.filter_by(
        user_id=current_user.id,
        question_id=eq.question_id
    ).count()
    
    return render_template(
        "exam_question.html",
        session=session,
        question=eq.question,
        current_index=index,
        total=total,
        index=index,
        review_count=review_count
    )


@exam_bp.route("/exam/<int:session_id>/answer_status")
@login_required
def exam_answer_status(session_id):
    """获取考试答题状态（AJAX接口）"""
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        return jsonify({"success": False, "message": "考试不存在"}), 404
    
    # 获取所有题目的答题状态
    exam_questions = ExamQuestion.query.filter_by(session_id=session_id).order_by(
        ExamQuestion.order_index.asc()
    ).all()
    
    statuses = []
    for eq in exam_questions:
        statuses.append({
            "index": eq.order_index + 1,
            "question_id": eq.question_id,
            "is_correct": eq.is_correct if eq.user_answer else None,
            "answered": bool(eq.user_answer)
        })
    
    return jsonify({"success": True, "statuses": statuses})


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


@exam_bp.route("/exam/question/<int:question_id>/ai_explanation")
@login_required
def get_ai_explanation(question_id):
    """获取题目的 AI 解析（AJAX接口）"""
    question = db.session.get(Question, question_id)
    if not question:
        return jsonify({"success": False, "message": "题目不存在"}), 404
    
    if not question.ai_explanation:
        return jsonify({"success": False, "message": "该题目暂无 AI 解析"}), 404
    
    # 返回渲染后的 HTML
    ai_html = str(render_markdown(question.ai_explanation))
    
    return jsonify({"success": True, "ai_explanation": ai_html})


@exam_bp.route("/exam/<int:session_id>/<int:question_id>/add_to_today", methods=["POST"])
@login_required
def add_wrong_to_today_ajax(session_id, question_id):
    """将错题加入到今天的Anki复习中（AJAX接口）"""
    session = db.session.get(ExamSession, session_id)
    if not session or session.user_id != current_user.id:
        return jsonify({"success": False, "message": "考试不存在"}), 404
    
    # 检查该题目是否属于这次考试
    eq = ExamQuestion.query.filter_by(
        session_id=session_id, 
        question_id=question_id
    ).first()
    
    if not eq:
        return jsonify({"success": False, "message": "题目不属于本次考试"}), 404
    
    try:
        # 更新或创建Anki卡片，将下次复习时间设为今天
        card = AnkiCard.query.filter_by(
            user_id=current_user.id, 
            question_id=question_id
        ).first()
        
        if not card:
            card = AnkiCard(
                user_id=current_user.id,
                question_id=question_id,
                interval_days=0.0,
                ease=2.5,
                repetitions=0,
                next_review_at=_now_shanghai(),
                last_reviewed_at=None
            )
            db.session.add(card)
        else:
            card.next_review_at = _now_shanghai()
            card.interval_days = 0.0
            card.repetitions = 0
        
        db.session.commit()
        return jsonify({"success": True, "message": "已将该题加入到今天的复习中"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"操作失败: {str(e)}"}), 500


@exam_bp.route("/exam/history")
@login_required
def exam_history():
    """查看所有考试记录"""
    sessions = ExamSession.query.filter_by(user_id=current_user.id).order_by(
        ExamSession.created_at.desc()
    ).all()
    
    return render_template("exam_history.html", sessions=sessions)