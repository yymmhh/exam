import json
import re

def convert_txt_to_json(input_file, output_file):
    """
    将 txt 格式的题目转换为 JSON 格式
    
    支持的题型：
    1. 单选题 - 有 A/B/C/D 选项
    2. 多选题 - 有 A/B/C/D 选项，答案为多个（如 A,B）
    3. 判断题 - 答案为 "正确"/"错误" 或 "对"/"错"，自动转换为单选题
    4. 填空题 - 没有选项
    
    输入格式示例：
    
    【单选题】
    1.题目内容
    A.选项A
    B.选项B
    C.选项C
    D.选项D
    答案：A
    解析：解析内容
    
    【判断题】
    1.题目内容
    答案：正确
    解析：解析内容
    
    【填空题】
    1.题目内容
    答案：填空答案
    解析：解析内容
    
    输出格式：
    [
      {
        "qtype": "single",  // 判断题也转为 single
        "stem": "题目内容",
        "options": {"A": "正确", "B": "错误"},  // 判断题自动添加
        "answer": "A",  // 标准化为选项字母
        "explanation": "解析内容"
      }
    ]
    """
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 按题目分割（匹配 "数字." 开头）
    questions_raw = re.split(r'\n(?=\d+\.)', content)
    
    questions = []
    
    for q_text in questions_raw:
        q_text = q_text.strip()
        if not q_text:
            continue
        
        try:
            # 提取题号
            match = re.match(r'^(\d+)\.', q_text)
            if not match:
                continue
            
            lines = q_text.split('\n')
            
            # 第一行是题干（去掉题号）
            stem = re.sub(r'^\d+\.', '', lines[0]).strip()
            
            # 提取选项
            options = {}
            answer_line_idx = None
            
            for i, line in enumerate(lines[1:], start=1):
                line = line.strip()
                
                # 检查是否是答案行
                if line.startswith('答案：'):
                    answer = line.replace('答案：', '').strip()
                    answer_line_idx = i
                    break
                
                # 检查是否是选项（A. xxx 或 A、xxx）
                option_match = re.match(r'^([A-Z])[.、]\s*(.+)', line)
                if option_match:
                    key = option_match.group(1)
                    value = option_match.group(2).strip()
                    options[key] = value
            
            # 如果没有找到答案，跳过
            if answer_line_idx is None:
                print(f"⚠️  跳过题目（未找到答案）：{stem[:30]}...")
                continue
            
            # 提取解析
            explanation = ""
            for line in lines[answer_line_idx + 1:]:
                line = line.strip()
                if line.startswith('解析：'):
                    explanation = line.replace('解析：', '').strip()
                    break
            
            # 判断题型并转换
            qtype, final_options, final_answer = process_question(answer, options)
            
            # 构建题目对象
            question = {
                "qtype": qtype,
                "stem": stem,
                "options": final_options,
                "answer": final_answer,
                "explanation": explanation
            }
            
            questions.append(question)
            
        except Exception as e:
            print(f"❌ 处理题目时出错：{e}")
            print(f"   题目内容：{q_text[:100]}...")
            continue
    
    # 保存为 JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    
    # 统计各题型数量
    type_count = {}
    for q in questions:
        qtype = q['qtype']
        type_count[qtype] = type_count.get(qtype, 0) + 1
    
    print("=" * 60)
    print(f"✅ 转换完成！")
    print(f"📄 输入文件：{input_file}")
    print(f"📄 输出文件：{output_file}")
    print(f"📊 总计：{len(questions)} 道题目")
    print(f"   - 单选题：{type_count.get('single', 0)} 道（含判断题）")
    print(f"   - 多选题：{type_count.get('multiple', 0)} 道")
    print(f"   - 填空题：{type_count.get('blank', 0)} 道")
    print("=" * 60)
    
    return len(questions)


def process_question(answer, options):
    """
    处理题目，判断题型并标准化
    
    Args:
        answer: 原始答案
        options: 原始选项字典
    
    Returns:
        tuple: (qtype, options, answer)
    """
    # 如果有选项，可能是单选或多选
    if options:
        # 检查答案是否包含逗号或顿号（多选题）
        if ',' in answer or '、' in answer:
            return ('multiple', options, normalize_multiple_answer(answer))
        else:
            return ('single', options, answer.upper())
    
    # 没有选项，检查是否是判断题
    if is_judgment_answer(answer):
        # 判断题转换为单选题，自动添加选项
        judgment_options = {
            "A": "正确",
            "B": "错误"
        }
        
        # 将答案转换为 A 或 B
        normalized_answer = convert_judgment_to_option(answer)
        
        return ('single', judgment_options, normalized_answer)
    
    # 默认是填空题
    return ('blank', {}, answer)


def is_judgment_answer(answer):
    """
    判断答案是否是判断题格式
    
    Args:
        answer: 答案字符串
    
    Returns:
        bool: 是否是判断题
    """
    judgment_keywords = ['正确', '错误', '对', '错', 'T', 'F', 'true', 'false', '√', '×']
    answer_lower = answer.lower()
    
    for keyword in judgment_keywords:
        if keyword.lower() in answer_lower:
            return True
    
    return False


def convert_judgment_to_option(answer):
    """
    将判断题答案转换为选项字母
    
    Args:
        answer: 原始答案（正确/错误/对/错等）
    
    Returns:
        str: A 或 B
    """
    answer_lower = answer.lower().strip()
    
    # 正确的各种表达
    if answer_lower in ['正确', '对', 't', 'true', '√']:
        return 'A'
    
    # 错误的各种表达
    elif answer_lower in ['错误', '错', 'f', 'false', '×']:
        return 'B'
    
    # 如果已经是 A 或 B，直接返回
    elif answer_lower in ['a', 'b']:
        return answer_lower.upper()
    
    # 默认返回 A
    return 'A'


def normalize_multiple_answer(answer):
    """
    标准化多选题答案
    
    Args:
        answer: 原始答案（如 "A,B,C" 或 "A、B、C"）
    
    Returns:
        str: 标准化后的答案（如 "A,B,C"）
    """
    # 分割答案
    parts = re.split(r'[，,、]', answer)
    # 清理并转大写
    normalized_parts = [p.strip().upper() for p in parts if p.strip()]
    # 排序并连接
    normalized_parts.sort()
    return ','.join(normalized_parts)


if __name__ == "__main__":
    input_file = "question.txt"
    output_file = "converted_questions.json"
    
    count = convert_txt_to_json(input_file, output_file)
    
    if count > 0:
        print("\n💡 使用方法：")
        print(f"1. 进入管理后台")
        print(f"2. 选择题库，点击 '📥 批量导入'")
        print(f"3. 选择 '📁 上传文件' 标签")
        print(f"4. 上传 {output_file} 文件")
        print(f"5. 点击 '🚀 开始导入'")