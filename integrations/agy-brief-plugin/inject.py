"""PreInvocation hook: inject project brief once per conversation.

Output schema (agy hooks_pb.PreInvocationHookResult): {"injectSteps": [{"userMessage": "<text>"}]}.
Fails open: any error -> {} (no injection).
"""
import json
import subprocess
import sys

BRIEF = "/Users/ryantruong/Project/personal-kb/scripts/project_brief.py"


def main():
    raw = sys.stdin.read()
    try:
        p = json.loads(raw)
        if p.get("invocationNum") != 0 or p.get("initialNumSteps") != 1:
            print("{}")
            return
        r = subprocess.run(["/usr/bin/python3", BRIEF, "--runtime", "agy", "--format", "text"],
                           input=raw, capture_output=True, text=True, timeout=10)
        text = r.stdout.strip()
        print(json.dumps({"injectSteps": [{"userMessage": text}]}, ensure_ascii=False) if text else "{}")
    except Exception:
        print("{}")


main()
