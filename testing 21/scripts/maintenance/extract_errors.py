import os
import re


def get_tracebacks():
    try:
        data = open('app.log', 'r', encoding='utf-8', errors='ignore').read()
        matches = re.findall(r'Traceback.*?(?=\d{4}-\d{2}-\d{2}|\Z)', data, re.DOTALL)
        if not matches:
            return "No traceback found in log"
        return '\n\n---\n\n'.join(matches[-5:])
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recent_errors.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(get_tracebacks())
