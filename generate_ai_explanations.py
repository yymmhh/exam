import json
import os
import sys
import urllib.error
import urllib.request
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Question, Choice

TENCENT_MAAS_API_URL = "https://tokenhub.tencentmaas.com/v1/chat/completions"
TENCENT_MAAS_MODEL = "deepseek-v4-pro-202606"


def build_ai_prompt(question: Question) -> str:
    """构建给 AI 的提示词"""
    choices_text = ""
    if question.qtype in ["single", "multiple"]:
        choices = Choice.query.filter_by(question_id=question.id).order_by(Choice.option_key.asc()).all()
        if choices:
            options = "\n".join([f"{c.option_key}. {c.option_text}" for c in choices])
            choices_text = f"\n\n选项：\n{options}"
    
    prompt = f"""你是一位专业的教育专家，请为以下题目生成详细的解析：

题目类型：{question.qtype}
题干：{question.stem}{choices_text}
正确答案：{question.correct_answer}

要求：
1. 详细解释为什么这个答案是正确的
2. 如果是选择题，分析每个选项的对错原因
3. 如果是填空题，解释答案的关键点
4. 语言简洁明了，适合学生学习
5. 可以适当使用 HTML 标签（如 <p>、<strong>、<ul>、<li>）来格式化内容，让解析更易读
6. 如有需要，可以使用 <img src="图片 URL"> 来插入示意图

请生成解析："""
    
    return prompt


def generate_ai_explanation(question: Question, api_key: str) -> tuple:
    """为单个题目生成 AI 解析"""
    try:
        prompt = build_ai_prompt(question)
        payload = {
            "model": TENCENT_MAAS_MODEL,
            "messages": [
                {"role": "system", "content": "你是一位专业的教育专家，擅长为各类考试题目撰写清晰、准确的解析。"},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 2000,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            TENCENT_MAAS_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        print("  正在调用腾讯云 API...")
        with urllib.request.urlopen(request, timeout=120) as response:
            status_code = response.status
            response_data = json.loads(response.read().decode("utf-8"))

        print(f"  响应状态码：{status_code}")

        choices = response_data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content", "").strip()
            if content:
                print(f"  生成成功，内容长度：{len(content)}")
                return True, content

        print("  错误：无法从响应中提取内容")
        print(f"  完整响应：{response_data}")
        return False, None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"  API 调用失败：状态码 {e.code}")
        print(f"  错误信息：{error_body}")
        return False, None
    except Exception as e:
        print(f"  处理出错：{type(e).__name__}: {e}")
        import traceback
        print(f"  详细错误：{traceback.format_exc()}")
        return False, None


def main():
    """主函数"""
    api_key = os.getenv("TENCENT_MAAS_API_KEY", "")
    if not api_key:
        print("错误：请设置环境变量 TENCENT_MAAS_API_KEY")
        print("使用方法：")
        print("  1. 创建 .env 文件，添加：TENCENT_MAAS_API_KEY=your_api_key")
        print("  2. 或者直接运行：set TENCENT_MAAS_API_KEY=your_api_key && python generate_ai_explanations.py")
        sys.exit(1)
    
    with app.app_context():
        print("=" * 60)
        print("开始生成 AI 解析...")
        print("=" * 60)
        
        # 选择范围
        print("\n请选择要处理的题目范围：")
        print("1. 所有题目")
        print("2. 指定分类")
        print("3. 指定题目 ID（逗号分隔）")
        
        choice = input("\n请输入选项 (1/2/3): ").strip()
        
        questions = []
        
        if choice == "1":
            questions = Question.query.all()
        elif choice == "2":
            from app import Category
            categories = Category.query.order_by(Category.name.asc()).all()
            print("\n分类列表：")
            for idx, cat in enumerate(categories, 1):
                print(f"  {idx}. {cat.name} ({cat.id})")
            
            cat_input = input("\n请输入分类 ID: ").strip()
            if cat_input.isdigit():
                questions = Question.query.filter_by(category_id=int(cat_input)).all()
        elif choice == "3":
            ids_input = input("请输入题目 ID（逗号分隔，如：1,2,3,5）: ").strip()
            question_ids = [int(x.strip()) for x in ids_input.split(",") if x.strip().isdigit()]
            questions = Question.query.filter(Question.id.in_(question_ids)).all()
        
        if not questions:
            print("没有找到题目！")
            sys.exit(1)
        
        print(f"\n找到 {len(questions)} 道题目")
        print(f"模型：{TENCENT_MAAS_MODEL}")
        print(f"预计消耗时间：约 {len(questions) * 2} 秒")
        print("\n按 Enter 键开始，或输入 q 退出...")
        
        if input().strip().lower() == "q":
            print("已取消")
            sys.exit(0)
        
        total = len(questions)
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for idx, question in enumerate(questions, 1):
            print(f"\n[{idx}/{total}] 处理题目 ID: {question.id}")
            
            # 如果已有 AI 解析，询问是否跳过
            if question.ai_explanation and question.ai_explanation.strip():
                skip = input(f"  该题已有 AI 解析，是否跳过？(Y/n/skip-all): ").strip().lower()
                if skip != "n":
                    if skip == "skip-all":
                        skipped_count += 1
                        continue
                    skipped_count += 1
                    continue
            
            success, explanation = generate_ai_explanation(question, api_key)
            
            if success and explanation:
                question.ai_explanation = explanation
                db.session.commit()
                success_count += 1
                print(f"  ✓ 生成成功")
            else:
                failed_count += 1
                print(f"  ✗ 生成失败")
            
            # 简单延迟，避免请求过快
            import time
            time.sleep(0.5)
        
        print("\n" + "=" * 60)
        print("完成！")
        print(f"总计：{total} | 成功：{success_count} | 失败：{failed_count} | 跳过：{skipped_count}")
        print("=" * 60)


if __name__ == "__main__":
    main()