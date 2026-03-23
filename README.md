# 刷题 Web 网站（Flask）

## 功能

- 题库大类管理：一个大类下可包含多道题，支持单选、多选、填空。
- 练习模式：按题库练习，记录用户练习进度（做到第几题）和做题状态。
- 错题库：用户可将题目加入/移出错题库。
- 模拟考试：按题库随机抽题，提交后计算分数并判断是否及格（60 分）。
- 管理端：创建/删除题库大类，按大类导入题目，管理用户管理员权限。

## 技术栈

- Python + Flask
- SQLite + Flask-SQLAlchemy
- Flask-Login

## 运行步骤

1. 创建并激活虚拟环境（可选）：
   - Windows PowerShell:
     - `python -m venv .venv`
     - `.\.venv\Scripts\Activate.ps1`
2. 安装依赖：
   - `pip install -r requirements.txt`
3. 启动：
   - `python app.py`
4. 打开浏览器：
   - [http://127.0.0.1:5000](http://127.0.0.1:5000)

## 独立转换/导入脚本

新增脚本：`import_questions.py`

- 仅转换（生成标准 JSON）：
  - `python import_questions.py --input question.json --output normalized_questions.json`
- 转换并导入数据库：
  - `python import_questions.py --input question.json --output normalized_questions.json --import-db`
- 指定导入分类名：
  - `python import_questions.py --import-db --category my_bank`

## 默认管理员

- 用户名：`admin`
- 密码：`admin123`

首次运行会自动创建数据库和默认管理员。

## 导题格式（管理端 JSON）

管理端进入某个分类后，可粘贴 JSON 数组导入，例如：

```json
[
  {
    "qtype": "single",
    "stem": "Python 中用于定义函数的关键字是？",
    "options": {"A": "func", "B": "def", "C": "lambda"},
    "answer": "B",
    "explanation": "def 用于定义函数。"
  },
  {
    "qtype": "multiple",
    "stem": "以下哪些是 Python 基本数据类型？",
    "options": {"A": "list", "B": "dict", "C": "table"},
    "answer": "A,B",
    "explanation": "list 和 dict 都是基础类型。"
  },
  {
    "qtype": "blank",
    "stem": "Python 之父是 ____。",
    "answer": "Guido van Rossum",
    "explanation": "这是常识题。"
  }
]
```
