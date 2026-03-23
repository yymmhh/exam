import argparse
import json
from pathlib import Path

from app import Category, Choice, Question, app, db, init_db


def parse_source(raw: dict) -> list[dict]:
    problems = raw.get("data", {}).get("problem", [])
    normalized = []
    for item in problems:
        tm = item.get("tm", {}) or {}
        daan = item.get("daan", []) or []

        stem = str(tm.get("title", "")).strip()
        explanation = str(tm.get("examAnalysis", "")).strip()
        answers_raw = str(tm.get("answers", "")).strip().replace("，", ",")
        if not stem or not answers_raw:
            continue

        options = {}
        for d in daan:
            key = str(d.get("optionTag", "")).strip().upper()
            value = str(d.get("content", "")).strip()
            if key and value:
                options[key] = value

        answer_tokens = [x.strip().upper() for x in answers_raw.split(",") if x.strip()]
        if options:
            qtype = "multiple" if len(answer_tokens) > 1 else "single"
            answer = ",".join(answer_tokens)
        else:
            qtype = "blank"
            answer = answers_raw

        row = {
            "qtype": qtype,
            "stem": stem,
            "answer": answer,
            "explanation": explanation,
        }
        if options:
            row["options"] = options
        normalized.append(row)
    return normalized


def convert_file(input_path: Path, output_path: Path) -> list[dict]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    normalized = parse_source(raw)
    output_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return normalized


def import_to_db(rows: list[dict], category_name: str, description: str) -> tuple[int, int]:
    with app.app_context():
        init_db()
        category = Category.query.filter_by(name=category_name).first()
        if not category:
            category = Category(name=category_name, description=description)
            db.session.add(category)
            db.session.flush()

        inserted = 0
        for row in rows:
            q = Question(
                category_id=category.id,
                qtype=row["qtype"],
                stem=row["stem"],
                correct_answer=row["answer"],
                explanation=row.get("explanation", ""),
            )
            db.session.add(q)
            db.session.flush()
            for k, v in row.get("options", {}).items():
                db.session.add(Choice(question_id=q.id, option_key=k, option_text=v))
            inserted += 1

        db.session.commit()
        return inserted, category.id


def main():
    parser = argparse.ArgumentParser(
        description="Convert question.json to normalized format and optionally import into exam.db."
    )
    parser.add_argument(
        "--input",
        default="question.json",
        help="Source JSON path. Default: question.json",
    )
    parser.add_argument(
        "--output",
        default="normalized_questions.json",
        help="Normalized output path. Default: normalized_questions.json",
    )
    parser.add_argument(
        "--category",
        default="question_json_import",
        help="Category name for DB import. Default: question_json_import",
    )
    parser.add_argument(
        "--description",
        default="Imported by import_questions.py",
        help="Category description for DB import.",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        help="If set, import normalized rows into SQLite database.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    rows = convert_file(input_path, output_path)
    print(f"Converted: {len(rows)} questions -> {output_path}")

    if args.import_db:
        inserted, category_id = import_to_db(rows, args.category, args.description)
        print(
            f"Imported into DB: {inserted} questions, category='{args.category}', category_id={category_id}"
        )


if __name__ == "__main__":
    main()
