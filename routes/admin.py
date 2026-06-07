import json as json_module
import uuid
import os
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User, Category, Question, Choice, PracticeProgress, WrongQuestion
from utils import allowed_file


admin_bp = Blueprint('admin', __name__)


def admin_required():
    """检查是否为管理员"""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("需要管理员权限。", "error")
        return False
    return True


@admin_bp.route("/admin")
@login_required
def admin_home():
    if not admin_required():
        return redirect(url_for("index"))
    categories = Category.query.order_by(Category.sort_order.asc(), Category.id.asc()).all()
    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin_home.html", categories=categories, users=users)


@admin_bp.route("/admin/users")
@login_required
def admin_users():
    if not admin_required():
        return redirect(url_for("index"))
    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/admin/category/add", methods=["POST"])
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
        return redirect(url_for("admin.admin_home"))
    if Category.query.filter_by(name=name).first():
        flash("分类已存在。", "error")
        return redirect(url_for("admin.admin_home"))
    db.session.add(Category(name=name, description=desc, sort_order=sort_order, is_active=True))
    db.session.commit()
    flash("分类已创建。", "success")
    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/admin/category/edit/<int:category_id>", methods=["POST"])
@login_required
def admin_category_edit(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    sort_order_raw = request.form.get("sort_order", "0").strip()
    sort_order = int(sort_order_raw) if sort_order_raw.lstrip("-").isdigit() else 0
    if not name:
        flash("分类名不能为空。", "error")
        return redirect(url_for("admin.admin_home"))
    conflict = Category.query.filter(Category.name == name, Category.id != category_id).first()
    if conflict:
        flash("分类名已存在。", "error")
        return redirect(url_for("admin.admin_home"))
    category.name = name
    category.description = desc
    category.sort_order = sort_order
    db.session.commit()
    flash("分类已更新。", "success")
    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/admin/category/toggle/<int:category_id>", methods=["POST"])
@login_required
def admin_category_toggle(category_id):
    """切换分类的启用/禁用状态"""
    if not admin_required():
        return jsonify({"success": False, "message": "无权限"}), 403
    
    category = db.session.get(Category, category_id)
    if not category:
        return jsonify({"success": False, "message": "分类不存在"}), 404
    
    # 切换状态
    category.is_active = not category.is_active
    db.session.commit()
    
    status_text = "启用" if category.is_active else "禁用"
    return jsonify({
        "success": True, 
        "message": f"分类已{status_text}",
        "is_active": category.is_active
    })


@admin_bp.route("/admin/category/delete/<int:category_id>", methods=["POST"])
@login_required
def admin_category_delete(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    if Question.query.filter_by(category_id=category_id).count() > 0:
        flash("该分类下有题目，不能删除。", "error")
        return redirect(url_for("admin.admin_home"))
    db.session.delete(category)
    db.session.commit()
    flash("分类已删除。", "success")
    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/admin/questions/<int:category_id>")
@login_required
def admin_questions(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    questions = Question.query.filter_by(category_id=category_id).order_by(Question.id.asc()).all()
    return render_template("admin_questions.html", category=category, questions=questions)


@admin_bp.route("/admin/question/edit/<int:question_id>", methods=["GET", "POST"])
@login_required
def admin_question_edit(question_id):
    if not admin_required():
        return redirect(url_for("index"))
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    
    if request.method == "POST":
        qtype = request.form.get("qtype", "").strip()
        stem = request.form.get("stem", "").strip()
        answer = request.form.get("answer", "").strip()
        explanation = request.form.get("explanation", "").strip()
        ai_explanation = request.form.get("ai_explanation", "").strip()
        
        if qtype not in ("single", "multiple", "blank") or not stem or not answer:
            flash("请完整填写题型、题干、答案。", "error")
            return redirect(url_for("admin.admin_question_edit", question_id=question_id))

        question.qtype = qtype
        question.stem = stem
        question.correct_answer = answer
        question.explanation = explanation
        question.ai_explanation = ai_explanation

        if qtype in ("single", "multiple"):
            Choice.query.filter_by(question_id=question.id).delete()
            
            options_data = {}
            has_indexed = False
            
            for key, value in request.form.items():
                if key.startswith("option_key_"):
                    parts = key.split("_")
                    if len(parts) >= 3:
                        idx = parts[2]
                        if idx not in options_data:
                            options_data[idx] = {'key': None, 'text': None}
                        options_data[idx]['key'] = value
                        has_indexed = True
                
                elif key.startswith("option_text_"):
                    parts = key.split("_")
                    if len(parts) >= 3:
                        idx = parts[2]
                        if idx not in options_data:
                            options_data[idx] = {'key': None, 'text': None}
                        options_data[idx]['text'] = value
                        has_indexed = True
            
            if has_indexed:
                sorted_indices = sorted(options_data.keys(), 
                                       key=lambda x: int(x) if x and x.isdigit() else 999)
                
                for idx in sorted_indices:
                    opt_key = options_data[idx]['key']
                    opt_text = options_data[idx]['text']
                    
                    if opt_key and opt_key.strip() and opt_text and opt_text.strip():
                        db.session.add(Choice(
                            question_id=question.id,
                            option_key=opt_key.strip().upper(),
                            option_text=opt_text.strip()
                        ))
            else:
                option_keys = request.form.getlist("option_key")
                option_values = request.form.getlist("option_text")
                for key, value in zip(option_keys, option_values):
                    k = key.strip().upper()
                    v = value.strip()
                    if k and v:
                        db.session.add(Choice(question_id=question.id, option_key=k, option_text=v))
        else:
            Choice.query.filter_by(question_id=question.id).delete()

        db.session.commit()
        flash("题目已更新。", "success")
        return redirect(url_for("admin.admin_questions", category_id=question.category_id))

    choices = Choice.query.filter_by(question_id=question.id).order_by(Choice.option_key.asc()).all()
    return render_template("admin_question_edit.html", question=question, choices=choices)


@admin_bp.route("/admin/question/delete/<int:question_id>", methods=["POST"])
@login_required
def admin_question_delete(question_id):
    if not admin_required():
        return redirect(url_for("index"))
    question = db.session.get(Question, question_id)
    if not question:
        flash("题目不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    category_id = question.category_id
    Choice.query.filter_by(question_id=question.id).delete()
    PracticeProgress.query.filter_by(question_id=question.id).delete()
    WrongQuestion.query.filter_by(question_id=question.id).delete()
    db.session.delete(question)
    db.session.commit()
    flash("题目已删除。", "success")
    return redirect(url_for("admin.admin_questions", category_id=category_id))


@admin_bp.route("/admin/import/<int:category_id>", methods=["GET", "POST"])
@login_required
def admin_import_questions(category_id):
    if not admin_required():
        return redirect(url_for("index"))
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin.admin_home"))

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content:
            flash("导入内容不能为空。", "error")
            return redirect(url_for("admin.admin_import_questions", category_id=category_id))
        try:
            data = json_module.loads(content)
            imported = 0
            for row in data:
                qtype = row.get("qtype", "").strip()
                stem = row.get("stem", "").strip()
                answer = str(row.get("answer", "")).strip()
                explanation = str(row.get("explanation", "")).strip()
                ai_explanation = str(row.get("ai_explanation", "")).strip()
                options = row.get("options", {})
                if qtype not in ("single", "multiple", "blank") or not stem or not answer:
                    continue
                q = Question(
                    category_id=category_id,
                    qtype=qtype,
                    stem=stem,
                    correct_answer=answer,
                    explanation=explanation,
                    ai_explanation=ai_explanation if ai_explanation else None
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
            return redirect(url_for("admin.admin_home"))
        except Exception as ex:
            flash(f"导入失败: {ex}", "error")
            return redirect(url_for("admin.admin_import_questions", category_id=category_id))

    sample = """[
  {
    "qtype": "single",
    "stem": "Python 中用于定义函数的关键字是？",
    "options": {"A": "func", "B": "def", "C": "lambda"},
    "answer": "B",
    "explanation": "def 用于定义函数。"
  }
]"""
    return render_template("admin_import.html", category=category, sample=sample)


@admin_bp.route("/admin/import-file/<int:category_id>", methods=["POST"])
@login_required
def admin_import_questions_file(category_id):
    if not admin_required():
        return jsonify({'success': False, 'error': '无权限'}), 403
    
    category = db.session.get(Category, category_id)
    if not category:
        flash("分类不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    
    if 'json_file' not in request.files:
        flash("请上传 JSON 文件。", "error")
        return redirect(url_for("admin.admin_import_questions", category_id=category_id))
    
    json_file = request.files['json_file']
    
    if json_file.filename == '':
        flash("未选择文件。", "error")
        return redirect(url_for("admin.admin_import_questions", category_id=category_id))
    
    try:
        questions_data = json_module.load(json_file.stream)
        
        if not isinstance(questions_data, list):
            flash("JSON 文件格式错误，应该是题目数组。", "error")
            return redirect(url_for("admin.admin_import_questions", category_id=category_id))
        
        imported_count = 0
        error_count = 0
        
        for q_data in questions_data:
            try:
                if not all(k in q_data for k in ['qtype', 'stem', 'answer']):
                    error_count += 1
                    continue
                
                question = Question(
                    stem=q_data['stem'],
                    qtype=q_data['qtype'],
                    correct_answer=q_data['answer'],
                    explanation=q_data.get('explanation', ''),
                    ai_explanation=q_data.get('ai_explanation', ''),
                    category_id=category.id
                )
                db.session.add(question)
                db.session.flush()
                
                if 'options' in q_data and isinstance(q_data['options'], dict):
                    for opt_key, opt_text in q_data['options'].items():
                        choice = Choice(
                            question_id=question.id,
                            option_key=opt_key.strip().upper(),
                            option_text=str(opt_text)
                        )
                        db.session.add(choice)
                
                imported_count += 1
                
            except Exception as e:
                error_count += 1
                print(f"导入题目失败: {e}")
                continue
        
        db.session.commit()
        
        if imported_count > 0:
            flash(f"成功导入 {imported_count} 道题目！{'失败 ' + str(error_count) + ' 道' if error_count > 0 else ''}", "success")
        else:
            flash("没有成功导入任何题目，请检查 JSON 格式。", "error")
        
        return redirect(url_for("admin.admin_questions", category_id=category.id))
        
    except json_module.JSONDecodeError:
        flash("JSON 文件格式错误，无法解析。", "error")
        return redirect(url_for("admin.admin_import_questions", category_id=category_id))
    except Exception as e:
        flash(f"导入失败：{str(e)}", "error")
        return redirect(url_for("admin.admin_import_questions", category_id=category_id))


@admin_bp.route("/admin/question/add", methods=["GET", "POST"])
@login_required
def admin_question_add():
    """添加题目（带图片上传）"""
    from flask import current_app
    import uuid
    
    if not admin_required():
        return redirect(url_for("index"))
    
    categories = Category.query.order_by(Category.sort_order.asc()).all()
    
    if request.method == "POST":
        category_id = request.form.get("category_id", type=int)
        qtype = request.form.get("qtype", "").strip()
        stem = request.form.get("stem", "").strip()
        answer = request.form.get("answer", "").strip()
        explanation = request.form.get("explanation", "").strip()
        ai_explanation = request.form.get("ai_explanation", "").strip()
        
        if not all([category_id, qtype, stem, answer]):
            flash("请完整填写所有必填字段。", "error")
            return redirect(url_for("admin.admin_question_add"))
        
        # 处理图片上传
        uploaded_images = []
        for key in request.files:
            file = request.files[key]
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower()
                unique_name = f"{uuid.uuid4().hex}.{ext}"
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name)
                file.save(filepath)
                uploaded_images.append(unique_name)
        
        # 替换题干中的图片标记
        for img_name in uploaded_images:
            stem = stem.replace(f"[[IMAGE:{img_name}]]", f"![图片](/static/exam_images/{img_name})")
        
        question = Question(
            category_id=category_id,
            qtype=qtype,
            stem=stem,
            correct_answer=answer,
            explanation=explanation,
            ai_explanation=ai_explanation
        )
        db.session.add(question)
        db.session.flush()
        
        if qtype in ("single", "multiple"):
            option_keys = request.form.getlist("option_key")
            option_values = request.form.getlist("option_text")
            for key, value in zip(option_keys, option_values):
                k = key.strip().upper()
                v = value.strip()
                if k and v:
                    db.session.add(Choice(question_id=question.id, option_key=k, option_text=v))
        
        db.session.commit()
        flash("题目已添加。", "success")
        return redirect(url_for("admin.admin_questions", category_id=category_id))
    
    return render_template("admin_question_add.html", categories=categories)



@admin_bp.route("/admin/upload-image", methods=["POST"])
@login_required
def admin_upload_image():
    """上传图片"""
    if not admin_required():
        return jsonify({'success': False, 'error': '无权限'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '没有文件'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': '未选择文件'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '不支持的文件类型'}), 400
    
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    
    try:
        file.save(filepath)
        return jsonify({
            'success': True,
            'filename': unique_name,
            'url': f"/static/exam_images/{unique_name}"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route("/admin/user/toggle_admin/<int:user_id>", methods=["POST"])
@login_required
def admin_toggle_user(user_id):
    if not admin_required():
        return redirect(url_for("index"))
    user = db.session.get(User, user_id)
    if not user:
        flash("用户不存在。", "error")
        return redirect(url_for("admin.admin_home"))
    if user.id == current_user.id:
        flash("不能修改自己管理员状态。", "error")
        return redirect(url_for("admin.admin_home"))
    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"已更新用户 {user.username} 管理员状态。", "success")
    return redirect(url_for("admin.admin_home"))


@admin_bp.route("/admin/user/add", methods=["POST"])
@login_required
def admin_user_add():
    if not admin_required():
        return redirect(url_for("index"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    is_admin = request.form.get("is_admin") == "on"
    if not username or not password:
        flash("用户名和密码不能为空。", "error")
        return redirect(url_for("admin.admin_home"))
    if User.query.filter_by(username=username).first():
        flash("用户名已存在。", "error")
        return redirect(url_for("admin.admin_home"))
    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"用户 {username} 已创建。", "success")
    return redirect(url_for("admin.admin_home"))