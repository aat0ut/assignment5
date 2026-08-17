import json
import requests

with open("evals/cases.json") as f:
    cases = json.load(f)

correct = 0
failures = []

for case in cases:
    resp = requests.post(
        "http://localhost:8000/triage",
        json={"text": case["input"]},
        timeout=35,
    )
    if resp.status_code != 200:
        failures.append({"input": case["input"], "error": f"status {resp.status_code}"})
        continue
    result = resp.json()
    actual = result.get("category")
    expected = case["expected_category"]
    if actual == expected:
        correct += 1
    else:
        failures.append({
            "input": case["input"],
            "expected": expected,
            "actual": actual
        })

print(f"\n{correct}/{len(cases)} correct\n")
if failures:
    print("Failures:")
    for f_ in failures:
        print(f"  {f_}")
