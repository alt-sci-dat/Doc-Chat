"""
Eval harness for DocChat.

Usage:
    python eval/eval.py --api-url http://localhost:8000 --questions eval/questions.json --output eval/results.csv

Reads questions.json, sends each question to /chat, records response metrics,
and writes results CSV with a "Manual Grade" column for human scoring.
"""

import argparse
import csv
import json
import time
import sys

import requests


def load_questions(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def run_question(q: dict, api_url: str, session_id: str) -> dict:
    question = q["question"]
    start = time.perf_counter()
    try:
        resp = requests.post(
            f"{api_url}/chat",
            json={"question": question, "session_id": session_id},
            timeout=30,
        )
        elapsed = round(time.perf_counter() - start, 2)

        if not resp.ok:
            return {
                "id": q["id"],
                "question": question[:100],
                "category": q["category"],
                "answer": f"HTTP {resp.status_code}",
                "citations_count": 0,
                "refusal": False,
                "time_sec": elapsed,
                "error": f"http_{resp.status_code}",
            }

        data = resp.json()
        answer = data.get("answer", "")
        citations = data.get("citations", [])
        is_refusal = "can't find this" in answer.lower()

        return {
            "id": q["id"],
            "question": question[:100],
            "category": q["category"],
            "answer": answer[:300],
            "citations_count": len(citations),
            "refusal": is_refusal,
            "time_sec": elapsed,
            "error": "",
        }

    except requests.ConnectionError:
        return {
            "id": q["id"],
            "question": question[:100],
            "category": q["category"],
            "answer": "",
            "citations_count": 0,
            "refusal": False,
            "time_sec": 0,
            "error": "connection_error",
        }
    except Exception as e:
        return {
            "id": q["id"],
            "question": question[:100],
            "category": q["category"],
            "answer": "",
            "citations_count": 0,
            "refusal": False,
            "time_sec": 0,
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="DocChat Eval Harness")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--questions", default="eval/questions.json")
    parser.add_argument("--output", default="eval/results.csv")
    parser.add_argument("--session-id", default="eval-session")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    print(f"Loaded {len(questions)} questions from {args.questions}")

    results = []
    for q in questions:
        print(f"  [{q['id']:>2}] {q['category']:>12}: {q['question'][:60]}...", end=" ")
        sys.stdout.flush()
        result = run_question(q, args.api_url, args.session_id)
        status = "✓" if not result["error"] else f"✗ {result['error']}"
        print(f"{status} ({result['time_sec']}s)")

        results.append({
            "id": result["id"],
            "question": result["question"],
            "category": result["category"],
            "expected_refusal": q["expected_refusal"],
            "refusal_detected": result["refusal"],
            "answer": result["answer"],
            "citations_count": result["citations_count"],
            "time_sec": result["time_sec"],
            "error": result["error"],
            "manual_grade": "",
        })

    fieldnames = [
        "id", "question", "category", "expected_refusal", "refusal_detected",
        "answer", "citations_count", "time_sec", "error", "manual_grade",
    ]
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    refusal_correct = sum(
        1 for r in results if r["expected_refusal"] == r["refusal_detected"]
    )
    total = len(results)
    avg_time = sum(r["time_sec"] for r in results) / total if total else 0
    total_citations = sum(r["citations_count"] for r in results)

    print(f"\n{'='*50}")
    print(f"Results written to {args.output}")
    print(f"Refusal accuracy: {refusal_correct}/{total} ({refusal_correct/total*100:.0f}%)")
    print(f"Average response time: {avg_time:.2f}s")
    print(f"Total citations given: {total_citations}")

    failed = [r for r in results if r["error"]]
    if failed:
        print(f"Errors: {len(failed)}")
        for f in failed:
            print(f"  [{f['id']}] {f['error']}")


if __name__ == "__main__":
    main()
