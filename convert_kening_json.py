#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 kening.json 中的题目数组转换为考试系统可导入的 JSON 格式。

源字段:
  title    -> stem（题干）
  options  -> options（按 <br> 或换行切分，解析 A/B/C... 前缀）
  answer   -> answer（数字 1=A, 2=B, ...）
  analysis -> explanation（解析）

用法:
  python convert_kening_json.py
  python convert_kening_json.py kening.json kening_import.json
"""

import json
import re
import sys
from pathlib import Path


def split_options(raw: str) -> list[str]:
    """按 <br>、\\u003cbr\\u003e 或换行切分选项片段。"""
    if not raw:
        return []
    text = raw.replace("\u003cbr\u003e", "\n").replace("\u003cBR\u003e", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    parts = re.split(r"[\r\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def parse_options_dict(raw: str) -> dict[str, str]:
    """
    将 "A.正确<br>B.错误" 解析为 {"A": "正确", "B": "错误"}。
    若片段无字母前缀，则按顺序分配 A、B、C...
    """
    parts = split_options(raw)
    options: dict[str, str] = {}
    fallback_idx = 0

    for part in parts:
        m = re.match(r"^([A-Z])[\.、．:：\s]\s*(.*)$", part, re.IGNORECASE)
        if m:
            key = m.group(1).upper()
            options[key] = m.group(2).strip()
        else:
            while chr(ord("A") + fallback_idx) in options:
                fallback_idx += 1
            key = chr(ord("A") + fallback_idx)
            options[key] = part
            fallback_idx += 1

    return options


def numeric_answer_to_letter(answer) -> str:
    """1 -> A, 2 -> B；多选如 "1,3" -> "A,C"。"""
    if answer is None:
        return ""
    s = str(answer).strip()
    if not s:
        return ""

    letters: list[str] = []
    for token in re.split(r"[,，\s]+", s):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            n = int(token)
            if 1 <= n <= 26:
                letters.append(chr(ord("A") + n - 1))
            else:
                letters.append(token)
        elif re.fullmatch(r"[A-Za-z]", token):
            letters.append(token.upper())
        else:
            letters.append(token)

    if len(letters) > 1:
        return ",".join(letters)
    return letters[0] if letters else s


def convert_item(item: dict) -> dict | None:
    stem = (item.get("title") or "").strip()
    answer = numeric_answer_to_letter(item.get("answer"))
    if not stem or not answer:
        return None

    options = parse_options_dict(item.get("options") or "")
    qtype = "single" if options else "blank"

    row = {
        "qtype": qtype,
        "stem": stem,
        "answer": answer,
        "explanation": (item.get("analysis") or "").strip(),
    }
    if options:
        row["options"] = options
    return row


def convert_kening(data: list) -> list[dict]:
    result = []
    skipped = 0
    for item in data:
        row = convert_item(item)
        if row:
            result.append(row)
        else:
            skipped += 1
    if skipped:
        print(f"跳过 {skipped} 道无效题目（缺少题干或答案）")
    return result


def main():
    base = Path(__file__).resolve().parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "kening.json"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "kening_import.json"

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("错误: 根节点应为 JSON 数组")
        sys.exit(1)

    converted = convert_kening(data)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(converted, f, ensure_ascii=False, indent=2)

    print(f"已转换 {len(converted)} 道题")
    print(f"输出: {output_path}")


if __name__ == "__main__":
    main()
