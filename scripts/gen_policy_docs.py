"""Regenerate the policy section of .kiro/steering/policy.md from the rules YAML.

The system prompt injects the same text at startup (masshelp/rules/policy_text.py),
so the prompt, the steering doc, and the engine never disagree.
    uv run scripts/gen_policy_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from masshelp.config import PACKAGE_DIR  # noqa: E402
from masshelp.rules.models import load_rules  # noqa: E402
from masshelp.rules.policy_text import policy_markdown  # noqa: E402

STEERING = ROOT / ".kiro" / "steering" / "policy.md"
BEGIN, END = "<!-- BEGIN GENERATED POLICY -->", "<!-- END GENERATED POLICY -->"


def main() -> None:
    rules = load_rules(PACKAGE_DIR / "rules" / "masshealth_rules.yaml")  # validates the YAML too
    body = (f"{BEGIN}\n_Generated from masshelp/rules/masshealth_rules.yaml by scripts/gen_policy_docs.py. "
            f"Do not edit by hand._\n\n{policy_markdown(rules)}\n{END}")
    text = STEERING.read_text(encoding="utf-8")
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: body, text, flags=re.S)
    STEERING.write_text(new, encoding="utf-8")
    print(f"updated {STEERING.relative_to(ROOT)} (rules version {rules.version})")


if __name__ == "__main__":
    main()
