import random
import re
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from markupsafe import Markup
import markdown


# ==================== 时区配置 ====================
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _now_shanghai() -> datetime:
    """获取当前上海时间（naive datetime，不带时区信息）"""
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


def _default_now():
    """SQLAlchemy default 回调函数，返回上海时间"""
    return _now_shanghai()


# ==================== 答案处理工具 ====================
def normalize_answer(qtype, raw):
    """标准化用户答案"""
    if qtype == "blank":
        return (raw or "").strip()
    if isinstance(raw, list):
        return ",".join(sorted(set(r.strip().upper() for r in raw if r and r.strip())))
    return (raw or "").strip().upper()


def check_answer(question, user_answer):
    """检查答案是否正确"""
    if not user_answer:
        return False
    
    correct = question.correct_answer.strip().upper()
    user = user_answer.strip().upper()
    
    if question.qtype == "single":
        return user == correct
    elif question.qtype == "multiple":
        correct_set = set(c.strip() for c in correct.split(","))
        user_set = set(c.strip() for c in user.split(","))
        return correct_set == user_set
    elif question.qtype == "blank":
        # 填空题支持多种正确答案（用 | 分隔）
        correct_answers = [ans.strip() for ans in correct.split("|")]
        return user in correct_answers
    
    return False


# ==================== Markdown 渲染 ====================
def _markdown_to_html(text: str) -> str:
    """将 Markdown 文本转换为 HTML（含 LaTeX 公式支持）"""
    if not text:
        return ""
    
    # 处理 LaTeX 公式保护
    latex_blocks = []
    
    def save_latex(match):
        latex_blocks.append(match.group(0))
        return f"__LATEX_{len(latex_blocks)-1}__"
    
    # 保存 $$...$$ 和 \\[...\\]
    text = re.sub(r'\$\$(.+?)\$\$', save_latex, text, flags=re.DOTALL)
    text = re.sub(r'\\\[(.+?)\\\]', save_latex, text, flags=re.DOTALL)
    
    # 保存 $...$ 和 \\(...\\)
    text = re.sub(r'\$(.+?)\$', save_latex, text)
    text = re.sub(r'\\\((.+?)\\\)', save_latex, text)
    
    # 保存 ```latex 代码块
    text = re.sub(r'```latex\s*\n(.+?)\n```', save_latex, text, flags=re.DOTALL)
    
    # 转换 Markdown
    html_text = markdown.markdown(
        text,
        extensions=['fenced_code', 'tables']
    )
    
    # 恢复 LaTeX 公式
    for i, latex in enumerate(latex_blocks):
        placeholder = f"__LATEX_{i}__"
        html_text = html_text.replace(placeholder, latex)
    
    return html_text


def render_markdown(text: str) -> Markup:
    """模板过滤器：将 Markdown 文本渲染为 HTML"""
    return Markup(_markdown_to_html(text or ""))


def render_stem(stem: str) -> Markup:
    """渲染题干（处理 {blank} 占位符）"""
    if not stem:
        return Markup("")
    stem_html = _markdown_to_html(stem)
    stem_html = stem_html.replace("{blank}", '<span class="blank-placeholder">____</span>')
    return Markup(stem_html)


def render_explanation(explanation: str) -> Markup:
    """渲染解析"""
    return Markup(_markdown_to_html(explanation or ""))


def render_markdown_with_blanks(text: str) -> Markup:
    """渲染 Markdown 并处理 blank 占位符"""
    if not text:
        return Markup("")
    html_text = _markdown_to_html(text)
    html_text = html_text.replace("{blank}", '<input type="text" class="blank-input" placeholder="请填写答案">')
    return Markup(html_text)


# ==================== 文件上传工具 ====================
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ==================== Anki 相关常量 ====================
ANKI_RATING_LABELS = {
    "again": "重来",
    "hard": "困难",
    "good": "良好",
    "easy": "简单",
}
ANKI_AGAIN_MINUTES_RANGE = (5, 20)
ANKI_JITTER_DAYS_RANGE = (1, 3)
ANKI_STATS_TZ = ZoneInfo("Asia/Shanghai")
ANKI_RATING_CHART_KEYS = ("again", "hard", "good", "easy")


# ==================== Anki 辅助函数 ====================
def _anki_format_interval(days: float) -> str:
    """格式化时间间隔显示"""
    if days < 1 / 1440:
        return "<1 分钟"
    if days < 1:
        minutes = max(1, int(days * 24 * 60))
        return f"{minutes} 分钟"
    if days < 30:
        if days < 2:
            return f"{max(1, int(round(days)))} 天"
        return f"{int(round(days))} 天"
    months = days / 30
    if months < 12:
        return f"{months:.1f} 个月".replace(".0", "")
    years = days / 365
    return f"{years:.1f} 年".replace(".0", "")


def _anki_again_interval_minutes() -> int:
    """获取 again 的间隔分钟数"""
    return random.randint(*ANKI_AGAIN_MINUTES_RANGE)


def _anki_jitter_days() -> int:
    """获取抖动天数"""
    return random.randint(*ANKI_JITTER_DAYS_RANGE)


def _anki_base_interval_days(card, rating: str) -> float:
    """计算基础间隔天数"""
    ease = card.ease if card else 2.5
    reps = card.repetitions if card else 0
    interval = card.interval_days if card else 0.0

    if rating == "again":
        return 0.0
    if rating == "hard":
        if reps == 0:
            return 1.0
        return max(1.0, interval * 1.2)
    if rating == "good":
        if reps == 0:
            return 1.0
        return max(1.0, interval * ease)
    if rating == "easy":
        if reps == 0:
            return 4.0
        return max(1.0, interval * ease * 1.3)
    return 1.0


def _anki_rating_interval_hint(rating: str, card) -> str:
    """获取评分按钮的间隔提示"""
    if rating == "again":
        lo, hi = ANKI_AGAIN_MINUTES_RANGE
        return f"{lo}-{hi} 分钟"
    if rating in ("good", "easy"):
        base = _anki_base_interval_days(card, rating)
        lo = base + ANKI_JITTER_DAYS_RANGE[0]
        hi = base + ANKI_JITTER_DAYS_RANGE[1]
        return f"约 {_anki_format_interval(lo)}-{_anki_format_interval(hi)}"
    return _anki_format_interval(_anki_preview_interval(card, rating))


def _anki_preview_interval(card, rating: str) -> float:
    """预览间隔"""
    if rating == "again":
        avg_minutes = sum(ANKI_AGAIN_MINUTES_RANGE) / 2
        return avg_minutes / (24 * 60)
    if rating in ("good", "easy"):
        base = _anki_base_interval_days(card, rating)
        avg_jitter = sum(ANKI_JITTER_DAYS_RANGE) / 2
        return base + avg_jitter
    return _anki_base_interval_days(card, rating)


def _anki_apply_rating(card, rating: str) -> None:
    """应用评分到卡片"""
    now = _now_shanghai()
    if rating == "again":
        card.interval_days = 0.0
        card.repetitions = 0
        card.ease = max(1.3, card.ease - 0.2)
        card.next_review_at = now + timedelta(minutes=_anki_again_interval_minutes())
    elif rating == "hard":
        if card.repetitions == 0:
            card.interval_days = 1.0
        else:
            card.interval_days = max(1.0, card.interval_days * 1.2)
        card.repetitions += 1
        card.ease = max(1.3, card.ease - 0.15)
        card.next_review_at = now + timedelta(days=card.interval_days)
    elif rating == "good":
        base = _anki_base_interval_days(card, "good")
        card.interval_days = base + _anki_jitter_days()
        card.repetitions += 1
        card.next_review_at = now + timedelta(days=card.interval_days)
    elif rating == "easy":
        base = _anki_base_interval_days(card, "easy")
        card.interval_days = base + _anki_jitter_days()
        card.repetitions += 1
        card.ease = min(3.0, card.ease + 0.15)
        card.next_review_at = now + timedelta(days=card.interval_days)
    card.last_reviewed_at = now


def _anki_local_today():
    """获取本地今天的日期"""
    from datetime import date
    return datetime.now(ANKI_STATS_TZ).date()


def _anki_utc_naive_range_for_local_dates(start, end_exclusive):
    """获取本地日期范围对应的 UTC 时间范围"""
    start_local = datetime.combine(start, datetime.min.time(), tzinfo=ANKI_STATS_TZ)
    end_local = datetime.combine(end_exclusive, datetime.min.time(), tzinfo=ANKI_STATS_TZ)
    start_utc = start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start_utc, end_utc


def _anki_local_date_from_utc_naive(dt):
    """从 UTC naive datetime 转换为本地日期"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ANKI_STATS_TZ).date()


def _anki_chart_day_label(d, today):
    """图表日期标签"""
    if d == today:
        return "今天"
    if d == today - timedelta(days=1):
        return "昨天"
    return f"{d.month}/{d.day}"


def _anki_parse_utc_naive(iso_value):
    """解析 ISO 格式的时间字符串"""
    if not iso_value:
        return None
    return datetime.fromisoformat(iso_value)