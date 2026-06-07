from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, current_user
import random
from datetime import date, datetime, timedelta
from models import db, Category, Question, AnkiCard, AnkiReviewLog, PracticeProgress, WrongQuestion
from utils import (
    _now_shanghai, ANKI_RATING_LABELS, ANKI_AGAIN_MINUTES_RANGE, 
    ANKI_JITTER_DAYS_RANGE, ANKI_STATS_TZ, ANKI_RATING_CHART_KEYS
)
from utils import (
    _anki_format_interval, _anki_again_interval_minutes, _anki_jitter_days,
    _anki_base_interval_days, _anki_rating_interval_hint, _anki_preview_interval,
    _anki_apply_rating, _anki_local_today, _anki_utc_naive_range_for_local_dates,
    _anki_local_date_from_utc_naive, _anki_chart_day_label, _anki_parse_utc_naive
)

anki_bp = Blueprint('anki', __name__)


def _anki_get_or_create_card(user_id, question_id):
    """获取或创建 Anki 卡片"""
    card = AnkiCard.query.filter_by(user_id=user_id, question_id=question_id).first()
    if not card:
        card = AnkiCard(
            user_id=user_id,
            question_id=question_id,
            next_review_at=_now_shanghai(),
        )
        db.session.add(card)
        db.session.flush()
    return card


def _anki_correct_question_ids(user_id):
    """获取用户答对的题目ID集合"""
    return {
        s.question_id
        for s in PracticeProgress.query.filter_by(
            user_id=user_id, answered=True, is_correct=True
        ).all()
    }


def _anki_pool_question_ids(user_id, category_ids):
    """获取题库中的所有题目ID"""
    query = Question.query.filter(Question.category_id.in_(category_ids))
    return [q.id for q in query.all()]


def _anki_pick_next_question_id(user_id, pool_ids):
    """按 next_review_at 排序获取下一个题目"""
    if not pool_ids:
        return None

    now = _now_shanghai()
    
    cards = (
        AnkiCard.query.filter(
            AnkiCard.user_id == user_id, 
            AnkiCard.question_id.in_(pool_ids)
        )
        .order_by(AnkiCard.next_review_at.asc())
        .all()
    )
    
    card_map = {c.question_id: c for c in cards}
    
    due_cards = []
    new_ids = []
    
    for qid in pool_ids:
        if qid in card_map:
            if card_map[qid].next_review_at <= now:
                due_cards.append((card_map[qid].next_review_at, qid))
        else:
            new_ids.append(qid)
    
    due_cards.sort(key=lambda x: x[0])
    
    if due_cards:
        return due_cards[0][1]
    
    if new_ids:
        return random.choice(new_ids)
    
    return None


def _anki_study_stats(user_id, pool_ids):
    """统计信息"""
    if not pool_ids:
        return {
            "total": 0, "due": 0, "new": 0, "learning": 0,
            "scheduled": 0, "mature": 0, "studied": 0,
        }
    
    now = _now_shanghai()
    cards = {
        c.question_id: c
        for c in AnkiCard.query.filter(
            AnkiCard.user_id == user_id, AnkiCard.question_id.in_(pool_ids)
        ).all()
    }
    
    due = sum(1 for qid in pool_ids if qid not in cards or cards[qid].next_review_at <= now)
    new = sum(1 for qid in pool_ids if qid not in cards)
    learning = sum(
        1 for qid in pool_ids
        if qid in cards and cards[qid].repetitions == 0 and cards[qid].next_review_at > now
    )
    scheduled = sum(
        1 for qid in pool_ids
        if qid in cards and cards[qid].repetitions > 0 and cards[qid].next_review_at > now
    )
    mature = sum(
        1 for qid in pool_ids
        if qid in cards and cards[qid].interval_days >= 21
    )
    studied = len(cards)
    
    return {
        "total": len(pool_ids),
        "due": due,
        "new": new,
        "learning": learning,
        "scheduled": scheduled,
        "mature": mature,
        "studied": studied,
    }


def _anki_session_stats():
    """会话统计"""
    return session.get("anki_session_stats") or {
        "reviewed": 0, "again": 0, "hard": 0, "good": 0, "easy": 0,
    }


def _anki_record_session_rating(rating):
    """记录会话评分"""
    stats = _anki_session_stats()
    stats["reviewed"] = stats.get("reviewed", 0) + 1
    if rating in ("again", "hard", "good", "easy"):
        stats[rating] = stats.get(rating, 0) + 1
    session["anki_session_stats"] = stats


def _anki_empty_rating_counts():
    """空评分计数"""
    return {"reviewed": 0, "again": 0, "hard": 0, "good": 0, "easy": 0}


def _anki_log_review(user_id, question_id, rating):
    """记录复习日志"""
    log = AnkiReviewLog(
        user_id=user_id,
        question_id=question_id,
        rating=rating,
        reviewed_at=_now_shanghai(),
    )
    db.session.add(log)
    db.session.flush()
    return log


def _anki_build_undo_state(user_id, question_id):
    """构建撤销状态"""
    existing_card = AnkiCard.query.filter_by(user_id=user_id, question_id=question_id).first()
    card_snapshot = None
    if existing_card:
        card_snapshot = {
            "interval_days": existing_card.interval_days,
            "ease": existing_card.ease,
            "repetitions": existing_card.repetitions,
            "next_review_at": existing_card.next_review_at.isoformat() if existing_card.next_review_at else None,
            "last_reviewed_at": existing_card.last_reviewed_at.isoformat() if existing_card.last_reviewed_at else None,
        }

    user_status = PracticeProgress.query.filter_by(user_id=user_id, question_id=question_id).first()
    user_status_snapshot = None
    if user_status:
        user_status_snapshot = {
            "answered": user_status.answered,
            "is_correct": user_status.is_correct,
            "last_answered_at": user_status.last_answered_at.isoformat() if user_status.last_answered_at else None,
        }

    return {
        "question_id": question_id,
        "card_was_new": existing_card is None,
        "card_snapshot": card_snapshot,
        "user_status_was_new": user_status is None,
        "user_status_snapshot": user_status_snapshot,
        "wrong_existed": WrongQuestion.query.filter_by(user_id=user_id, question_id=question_id).first() is not None,
    }


def _anki_undo_session_rating(rating):
    """撤销会话评分"""
    stats = _anki_session_stats()
    stats["reviewed"] = max(0, stats.get("reviewed", 0) - 1)
    if rating in ("again", "hard", "good", "easy"):
        stats[rating] = max(0, stats.get(rating, 0) - 1)
    session["anki_session_stats"] = stats


def _anki_undo_info():
    """获取撤销信息"""
    undo = session.get("anki_undo")
    if not undo:
        return None
    rating = undo.get("rating", "")
    return {
        "question_id": undo.get("question_id"),
        "rating": rating,
        "rating_label": ANKI_RATING_LABELS.get(rating, rating),
    }


def _anki_review_activity_stats(user_id, days=7):
    """复习活动统计"""
    today = _anki_local_today()
    start_date = today - timedelta(days=days - 1)
    start_utc, end_utc = _anki_utc_naive_range_for_local_dates(start_date, today + timedelta(days=1))

    logs = AnkiReviewLog.query.filter(
        AnkiReviewLog.user_id == user_id,
        AnkiReviewLog.reviewed_at >= start_utc,
        AnkiReviewLog.reviewed_at < end_utc,
    ).all()

    daily = []
    buckets = {}
    for i in range(days):
        d = start_date + timedelta(days=i)
        buckets[d] = {
            "date": d.isoformat(),
            "label": _anki_chart_day_label(d, today),
            **_anki_empty_rating_counts(),
        }

    for log in logs:
        d = _anki_local_date_from_utc_naive(log.reviewed_at)
        if d not in buckets:
            continue
        buckets[d]["reviewed"] += 1
        if log.rating in ANKI_RATING_CHART_KEYS:
            buckets[d][log.rating] += 1

    for i in range(days):
        daily.append(buckets[start_date + timedelta(days=i)])

    today_stats = buckets.get(today, {**_anki_empty_rating_counts(), "date": today.isoformat(), "label": "今天"})
    return {"today": today_stats, "daily": daily}


def _anki_future_schedule_stats(user_id, category_ids, days=30):
    """未来排期统计"""
    today = _anki_local_today()
    
    pool_ids = _anki_pool_question_ids(user_id, category_ids)
    if not pool_ids:
        return {
            "daily": [],
            "total_scheduled": 0,
        }
    
    cards = AnkiCard.query.filter(
        AnkiCard.user_id == user_id,
        AnkiCard.question_id.in_(pool_ids),
        AnkiCard.next_review_at.isnot(None)
    ).all()
    
    daily = []
    buckets = {}
    for i in range(days):
        d = today + timedelta(days=i)
        buckets[d] = 0
    
    for card in cards:
        if card.next_review_at:
            review_date = _anki_local_date_from_utc_naive(card.next_review_at)
            if review_date in buckets:
                buckets[review_date] += 1
    
    for i in range(days):
        d = today + timedelta(days=i)
        label = "今天" if i == 0 else f"{d.month}/{d.day}"
        daily.append({
            "date": d.isoformat(),
            "label": label,
            "count": buckets[d],
        })
    
    total_scheduled = sum(buckets.values())
    
    return {
        "daily": daily,
        "total_scheduled": total_scheduled,
    }


@anki_bp.route("/anki/start", methods=["GET", "POST"])
@login_required
def anki_start():
    # 只获取启用的分类
    categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order.asc(), Category.name.asc()).all()

    if request.method == "POST":
        category_ids_str = request.form.get("category_ids", "")
        if category_ids_str:
            category_ids = [int(cid) for cid in category_ids_str.split(",") if cid.strip()]
        else:
            category_ids = [c.id for c in categories]

        if not category_ids:
            flash("请至少选择一个题库。", "error")
            return redirect(url_for("anki.anki_start"))

        pool_ids = _anki_pool_question_ids(current_user.id, category_ids)
        if not pool_ids:
            flash("当前设置下没有可刷题目。", "error")
            return redirect(url_for("anki.anki_start"))

        session["anki_category_ids"] = category_ids
        session["anki_again_queue"] = []
        session["anki_session_stats"] = {
            "reviewed": 0, "again": 0, "hard": 0, "good": 0, "easy": 0,
        }
        session.pop("anki_current_question_id", None)
        session.pop("anki_undo", None)
        session.pop("anki_undo_reveal_question_id", None)
        return redirect(url_for("anki.anki_study"))

    category_stats = []
    for c in categories:
        pool = _anki_pool_question_ids(current_user.id, [c.id])
        category_stats.append({"category": c, "count": len(pool)})

    return render_template(
        "anki_start.html",
        categories=categories,
        category_stats=category_stats,
    )


@anki_bp.route("/anki/study")
@login_required
def anki_study():
    category_ids = session.get("anki_category_ids")
    if not category_ids:
        flash("请先选择刷题设置。", "info")
        return redirect(url_for("anki.anki_start"))

    pool_ids = _anki_pool_question_ids(current_user.id, category_ids)
    if not pool_ids:
        return render_template("anki_done.html", reason="empty", can_undo=False)

    reveal_qid = session.pop("anki_undo_reveal_question_id", None)
    if reveal_qid and reveal_qid in pool_ids:
        question_id = reveal_qid
        show_answer = True
    else:
        question_id = _anki_pick_next_question_id(current_user.id, pool_ids)
        show_answer = False

    if not question_id:
        return render_template(
            "anki_done.html",
            reason="completed",
            stats=_anki_study_stats(current_user.id, pool_ids),
            session_stats=_anki_session_stats(),
            can_undo=bool(session.get("anki_undo")),
            undo_info=_anki_undo_info(),
        )

    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("anki.anki_start"))

    session["anki_current_question_id"] = question_id
    card = AnkiCard.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    rating_buttons = []
    for key in ("again", "hard", "good", "easy"):
        rating_buttons.append(
            {
                "key": key,
                "label": ANKI_RATING_LABELS[key],
                "interval_hint": _anki_rating_interval_hint(key, card),
            }
        )

    stats = _anki_study_stats(current_user.id, pool_ids)
    again_count = len(session.get("anki_again_queue") or [])
    
    review_logs = AnkiReviewLog.query.filter_by(
        user_id=current_user.id,
        question_id=question_id
    ).order_by(AnkiReviewLog.reviewed_at.desc()).all()
    
    total_reviews = len(review_logs)
    
    history = []
    for log in review_logs[:50]:
        history.append({
            "rating": log.rating,
            "rating_label": ANKI_RATING_LABELS.get(log.rating, log.rating),
            "reviewed_at": log.reviewed_at.strftime("%Y-%m-%d %H:%M"),
        })

    return render_template(
        "anki_study.html",
        question=question,
        stats=stats,
        session_stats=_anki_session_stats(),
        again_count=again_count,
        rating_buttons=rating_buttons,
        show_answer=show_answer,
        can_undo=bool(session.get("anki_undo")),
        undo_info=_anki_undo_info(),
        total_reviews=total_reviews,
        history=history,
    )


@anki_bp.route("/anki/study/<int:question_id>/reveal", methods=["POST"])
@login_required
def anki_reveal(question_id):
    if session.get("anki_current_question_id") != question_id:
        return redirect(url_for("anki.anki_study"))

    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("anki.anki_start"))

    category_ids = session.get("anki_category_ids") or []
    pool_ids = _anki_pool_question_ids(current_user.id, category_ids)
    card = AnkiCard.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    rating_buttons = []
    for key in ("again", "hard", "good", "easy"):
        rating_buttons.append(
            {
                "key": key,
                "label": ANKI_RATING_LABELS[key],
                "interval_hint": _anki_rating_interval_hint(key, card),
            }
        )

    stats = _anki_study_stats(current_user.id, pool_ids)
    again_count = len(session.get("anki_again_queue") or [])
    
    review_logs = AnkiReviewLog.query.filter_by(
        user_id=current_user.id,
        question_id=question_id
    ).order_by(AnkiReviewLog.reviewed_at.desc()).all()
    
    total_reviews = len(review_logs)
    
    history = []
    for log in review_logs[:50]:
        history.append({
            "rating": log.rating,
            "rating_label": ANKI_RATING_LABELS.get(log.rating, log.rating),
            "reviewed_at": log.reviewed_at.strftime("%Y-%m-%d %H:%M"),
        })

    return render_template(
        "anki_study.html",
        question=question,
        stats=stats,
        session_stats=_anki_session_stats(),
        again_count=again_count,
        rating_buttons=rating_buttons,
        show_answer=True,
        can_undo=bool(session.get("anki_undo")),
        undo_info=_anki_undo_info(),
        total_reviews=total_reviews,
        history=history,
    )


@anki_bp.route("/anki/study/<int:question_id>/rate", methods=["POST"])
@login_required
def anki_rate(question_id):
    if session.get("anki_current_question_id") != question_id:
        return redirect(url_for("anki.anki_study"))

    rating = request.form.get("rating", "").strip()
    if rating not in ANKI_RATING_LABELS:
        flash("无效的评分。", "error")
        return redirect(url_for("anki.anki_study"))

    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("anki.anki_start"))

    undo_state = _anki_build_undo_state(current_user.id, question_id)
    undo_state["rating"] = rating
    undo_state["again_queue_before"] = list(session.get("anki_again_queue") or [])

    card = _anki_get_or_create_card(current_user.id, question_id)
    _anki_apply_rating(card, rating)
    _anki_record_session_rating(rating)
    review_log = _anki_log_review(current_user.id, question_id, rating)
    undo_state["review_log_id"] = review_log.id

    again_queue = session.get("anki_again_queue") or []
    again_queue = [qid for qid in again_queue if qid != question_id]
    if rating == "again":
        again_queue.append(question_id)
    session["anki_again_queue"] = again_queue

    user_status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    if not user_status:
        user_status = PracticeProgress(user_id=current_user.id, question_id=question_id)
        db.session.add(user_status)
    user_status.answered = True
    user_status.last_answered_at = _now_shanghai()
    if rating in ("good", "easy"):
        user_status.is_correct = True
        wrong = WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question_id
        ).first()
        if wrong:
            db.session.delete(wrong)
    elif rating in ("again", "hard"):
        user_status.is_correct = False
        if not WrongQuestion.query.filter_by(
            user_id=current_user.id, question_id=question_id
        ).first():
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))

    db.session.commit()
    session["anki_undo"] = undo_state
    session.pop("anki_current_question_id", None)
    return redirect(url_for("anki.anki_study"))


@anki_bp.route("/anki/undo", methods=["POST"])
@login_required
def anki_undo():
    undo = session.get("anki_undo")
    if not undo:
        flash("没有可撤销的操作。", "info")
        return redirect(url_for("anki.anki_study"))

    category_ids = session.get("anki_category_ids")
    if not category_ids:
        flash("请先选择刷题设置。", "info")
        return redirect(url_for("anki.anki_start"))

    question_id = undo["question_id"]
    rating = undo.get("rating", "")

    card = AnkiCard.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if undo.get("card_was_new"):
        if card:
            db.session.delete(card)
    elif card and undo.get("card_snapshot"):
        snap = undo["card_snapshot"]
        card.interval_days = snap["interval_days"]
        card.ease = snap["ease"]
        card.repetitions = snap["repetitions"]
        card.next_review_at = _anki_parse_utc_naive(snap.get("next_review_at")) or _now_shanghai()
        card.last_reviewed_at = _anki_parse_utc_naive(snap.get("last_reviewed_at"))

    review_log_id = undo.get("review_log_id")
    if review_log_id:
        log = db.session.get(AnkiReviewLog, review_log_id)
        if log and log.user_id == current_user.id:
            db.session.delete(log)

    _anki_undo_session_rating(rating)
    session["anki_again_queue"] = list(undo.get("again_queue_before") or [])

    user_status = PracticeProgress.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    if undo.get("user_status_was_new"):
        if user_status:
            db.session.delete(user_status)
    elif user_status and undo.get("user_status_snapshot"):
        snap = undo["user_status_snapshot"]
        user_status.answered = snap["answered"]
        user_status.is_correct = snap["is_correct"]
        user_status.last_answered_at = _anki_parse_utc_naive(snap.get("last_answered_at"))

    wrong = WrongQuestion.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if rating in ("good", "easy"):
        if undo.get("wrong_existed") and not wrong:
            db.session.add(WrongQuestion(user_id=current_user.id, question_id=question_id))
    elif rating in ("again", "hard"):
        if not undo.get("wrong_existed") and wrong:
            db.session.delete(wrong)

    db.session.commit()
    session.pop("anki_undo", None)
    session["anki_current_question_id"] = question_id
    session["anki_undo_reveal_question_id"] = question_id
    flash(f"已撤销上一题（{ANKI_RATING_LABELS.get(rating, rating)}），请重新选择复习时间。", "success")
    return redirect(url_for("anki.anki_study"))


@anki_bp.route("/anki/stats")
@login_required
def anki_stats():
    category_ids = session.get("anki_category_ids")
    if not category_ids:
        # 只获取启用的分类
        categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order.asc(), Category.name.asc()).all()
        category_ids = [c.id for c in categories]
        in_session = False
    else:
        in_session = True

    pool_ids = _anki_pool_question_ids(current_user.id, category_ids)
    stats = _anki_study_stats(current_user.id, pool_ids)
    session_stats = _anki_session_stats() if in_session else None
    activity_stats = _anki_review_activity_stats(current_user.id)
    future_schedule_stats = _anki_future_schedule_stats(current_user.id, category_ids, days=30)
    category_names = [
        c.name for c in Category.query.filter(Category.id.in_(category_ids), Category.is_active==True).all()
    ]

    return render_template(
        "anki_stats.html",
        stats=stats,
        session_stats=session_stats,
        activity_stats=activity_stats,
        future_schedule_stats=future_schedule_stats,
        rating_labels=ANKI_RATING_LABELS,
        category_names=category_names,
        in_session=in_session,
    )


@anki_bp.route("/anki/done")
@login_required
def anki_done():
    return render_template("anki_done.html", reason="manual")


@anki_bp.route("/anki/end", methods=["POST"])
@login_required
def anki_end():
    session_stats = _anki_session_stats()
    session.pop("anki_category_ids", None)
    session.pop("anki_again_queue", None)
    session.pop("anki_current_question_id", None)
    session.pop("anki_undo", None)
    return redirect(url_for("anki.anki_done"))