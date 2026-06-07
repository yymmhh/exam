from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user
import random
import re
from models import db, Category, Question, WrongQuestion, RandomPracticeSession, RandomPracticeQuestion, PracticeProgress
from utils import normalize_answer, check_answer, _now_shanghai

random_practice_bp = Blueprint('random_practice', __name__)


def get_smart_random_questions(user_id, category_ids, count=10, include_wrong=False, wrong_count=1):
    """智能抽取题目"""
    if not category_ids:
        all_categories = Category.query.all()
    else:
        all_categories = Category.query.filter(Category.id.in_(category_ids)).all()
    
    if not all_categories:
        return []
    
    done_question_ids = set(
        s.question_id for s in PracticeProgress.query.filter_by(user_id=user_id, answered=True).all()
    )
    
    wrong_question_ids = set(
        w.question_id for w in WrongQuestion.query.filter_by(user_id=user_id).all()
    )
    
    correct_question_ids = set(
        s.question_id for s in PracticeProgress.query.filter_by(user_id=user_id, answered=True, is_correct=True).all()
    )
    
    category_questions = {}
    
    for cat in all_categories:
        all_qs = Question.query.filter_by(category_id=cat.id).all()
        undone_qs = [q for q in all_qs if q.id not in done_question_ids]
        done_wrong_qs = [q for q in all_qs 
                        if q.id in done_question_ids and q.id not in correct_question_ids and q.id not in wrong_question_ids]
        wrong_qs = [q for q in all_qs if q.id in wrong_question_ids] if include_wrong else []
        correct_qs = [q for q in all_qs if q.id in correct_question_ids]
        
        category_questions[cat.id] = {
            'category': cat,
            'all': all_qs,
            'undone': undone_qs,
            'done_wrong': done_wrong_qs,
            'wrong': wrong_qs,
            'correct': correct_qs,
            'has_undone': len(undone_qs) > 0,
            'pick_count': 0
        }
    
    total_wrong_needed = 0
    if include_wrong and wrong_question_ids:
        total_wrong_needed = max(1, min(wrong_count, 10))
    
    normal_count = count - total_wrong_needed
    
    selected_questions = []
    selected_ids = set()
    
    for _ in range(normal_count):
        available_categories = []
        for cat_id, data in category_questions.items():
            available = [q for q in data['undone'] if q.id not in selected_ids]
            if not available:
                available = [q for q in data['done_wrong'] if q.id not in selected_ids]
            
            if available:
                available_categories.append({
                    'cat_id': cat_id,
                    'data': data,
                    'available': available,
                    'pick_count': data['pick_count']
                })
        
        if not available_categories:
            break
        
        available_categories.sort(key=lambda x: (x['pick_count'], random.random()))
        best_cat = available_categories[0]
        selected = random.choice(best_cat['available'])
        
        selected_questions.append(selected)
        selected_ids.add(selected.id)
        category_questions[best_cat['cat_id']]['pick_count'] += 1
    
    if len(selected_questions) < normal_count:
        remaining = normal_count - len(selected_questions)
        all_undone_remaining = [q for cat_id, data in category_questions.items() 
                               for q in data['undone'] if q.id not in selected_ids]
        
        if all_undone_remaining:
            additional = random.sample(all_undone_remaining, min(remaining, len(all_undone_remaining)))
            selected_questions.extend(additional)
    
    if total_wrong_needed > 0:
        all_wrongs = [q for cat_id, data in category_questions.items() 
                     for q in data['wrong'] if q.id not in selected_ids]
        
        if all_wrongs:
            wrong_selected = random.sample(all_wrongs, min(total_wrong_needed, len(all_wrongs)))
            selected_questions.extend(wrong_selected)
    
    random.shuffle(selected_questions)
    return selected_questions[:count]


@random_practice_bp.route("/random-practice/start", methods=["GET", "POST"])
@login_required
def random_practice_start():
    if request.method == "POST":
        category_ids_str = request.form.get("category_ids", "")
        
        if category_ids_str:
            category_ids = [int(cid) for cid in category_ids_str.split(",") if cid.strip()]
        else:
            category_ids = []
        
        count = int(request.form.get("count", "10"))
        include_wrong = request.form.get("include_wrong") == "1"
        wrong_count = int(request.form.get("wrong_count", "1"))
        
        picked = get_smart_random_questions(current_user.id, category_ids, count, include_wrong, wrong_count)
        
        if not picked:
            flash("所选题库暂无题目，无法开始练习。", "error")
            return redirect(url_for("index"))
        
        wrong_question_ids = set(
            w.question_id for w in WrongQuestion.query.filter_by(user_id=current_user.id).all()
        )
        
        session = RandomPracticeSession(
            user_id=current_user.id,
            total_count=len(picked),
            current_index=0,
        )
        db.session.add(session)
        db.session.flush()
        
        for idx, q in enumerate(picked):
            is_wrong = q.id in wrong_question_ids
            db.session.add(
                RandomPracticeQuestion(
                    session_id=session.id, 
                    question_id=q.id, 
                    order_index=idx,
                    is_wrong_review=is_wrong
                )
            )
        db.session.commit()
        
        return redirect(url_for("random_practice.random_practice_question", session_id=session.id, index=1))
    
    categories = Category.query.order_by(Category.sort_order.asc(), Category.name.asc()).all()
    return render_template("random_practice_start.html", categories=categories)


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>")
@login_required
def random_practice_question(session_id, index):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    if session.status != "in_progress":
        return redirect(url_for("random_practice.random_practice_finish", session_id=session.id))
    
    total = session.total_count
    if index < 1 or index > total:
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    if session.current_index != index - 1:
        session.current_index = index - 1
        db.session.commit()
    
    eq = RandomPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    items = RandomPracticeQuestion.query.filter_by(session_id=session_id).order_by(
        RandomPracticeQuestion.order_index.asc()
    ).all()
    questions = [it.question for it in items]
    
    practice_statuses = {it.question_id: it for it in items}
    
    is_wrong_review = eq.is_wrong_review
    
    historical_status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=eq.question.id
    ).first()
    
    has_submitted = eq.has_submitted
    
    return render_template(
        "random_practice_question.html",
        session=session,
        question=eq.question,
        questions=questions,
        statuses=practice_statuses,
        status=eq if has_submitted else None,
        is_wrong_review=is_wrong_review,
        historical_status=historical_status,
        current_index=session.current_index + 1,
        total=total,
        index=index,
    )


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>/submit", methods=["POST"])
@login_required
def random_practice_submit(session_id, index):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id or session.status != "in_progress":
        flash("练习状态无效。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    eq = RandomPracticeQuestion.query.filter_by(
        session_id=session_id, order_index=index - 1
    ).first()
    
    if not eq:
        flash("题目不存在。", "error")
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    question = eq.question
    if question.qtype == "multiple":
        raw = request.form.getlist("answer")
    else:
        raw = request.form.get("answer", "")
    
    answer = normalize_answer(question.qtype, raw)
    is_correct = None if question.qtype == "blank" else check_answer(question, answer)
    
    if question.qtype == "blank" and (not answer or not answer.strip()):
        eq.user_answer = ""
        eq.is_correct = False
        is_correct = False
    else:
        eq.user_answer = answer
        eq.is_correct = is_correct
    
    eq.has_submitted = True
    
    status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()
    
    if not status:
        status = PracticeProgress(
            user_id=current_user.id, 
            question_id=question.id,
            is_correct=is_correct
        )
        db.session.add(status)
    
    status.answered = True
    status.is_correct = is_correct
    status.answer = answer
    status.last_answered_at = _now_shanghai()
    
    wrong = WrongQuestion.query.filter_by(
        user_id=current_user.id, question_id=question.id
    ).first()
    
    if is_correct is True:
        if wrong:
            db.session.delete(wrong)
    elif is_correct is False:
        if not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question.id))
    
    db.session.commit()
    
    if question.qtype == "blank":
        if not answer or not answer.strip():
            flash("填空题未作答，已加入错题库，请查看答案解析。", "warning")
        else:
            flash("填空题已提交，请对比答案并自行评估。", "info")
    else:
        flash("回答正确！" if is_correct else "回答错误，已加入错题库。", "success" if is_correct else "error")
    
    return redirect(url_for("random_practice.random_practice_question", session_id=session.id, index=index))


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>/next", methods=["POST"])
@login_required
def random_practice_next(session_id, index):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    if session.status != "in_progress":
        return redirect(url_for("random_practice.random_practice_finish", session_id=session.id))
    
    next_index = index + 1
    if next_index > session.total_count:
        session.status = "finished"
        db.session.commit()
        return redirect(url_for("random_practice.random_practice_finish", session_id=session.id))
    
    session.current_index = next_index - 1
    db.session.commit()
    return redirect(url_for("random_practice.random_practice_question", session_id=session.id, index=next_index))


@random_practice_bp.route("/random-practice/<int:session_id>/<int:index>/prev", methods=["POST"])
@login_required
def random_practice_prev(session_id, index):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    if session.status != "in_progress":
        return redirect(url_for("random_practice.random_practice_finish", session_id=session.id))
    
    prev_index = max(1, index - 1)
    session.current_index = prev_index - 1
    db.session.commit()
    return redirect(url_for("random_practice.random_practice_question", session_id=session.id, index=prev_index))


@random_practice_bp.route("/random-practice/<int:session_id>/goto", methods=["POST"])
@login_required
def random_practice_goto(session_id):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    if session.status != "in_progress":
        return redirect(url_for("random_practice.random_practice_finish", session_id=session.id))
    
    target = request.form.get("target", "").strip()
    if not target.isdigit():
        return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=1))
    
    idx = int(target) - 1
    idx = max(0, min(idx, session.total_count - 1))
    session.current_index = idx
    db.session.commit()
    return redirect(url_for("random_practice.random_practice_question", session_id=session_id, index=idx + 1))


@random_practice_bp.route("/random-practice/<int:session_id>/finish")
@login_required
def random_practice_finish(session_id):
    session = db.session.get(RandomPracticeSession, session_id)
    if not session or session.user_id != current_user.id:
        flash("练习不存在。", "error")
        return redirect(url_for("random_practice.random_practice_start"))
    
    correct_count = RandomPracticeQuestion.query.filter_by(
        session_id=session.id, is_correct=True
    ).count()
    
    return render_template(
        "random_practice_finish.html",
        session=session,
        correct_count=correct_count,
    )