"""Prompts as code: prompt text lives in prompts/*.yaml, never in Python, so it is reviewed and edited on its own."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    system: str
    user_template: str

    def render_user(self, **variables: str) -> str:
        """Fill the $placeholders of the user template; a missing variable raises KeyError."""
        return Template(self.user_template).substitute(variables)


@cache
def load_prompt(name: str) -> Prompt:
    data = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return Prompt(name=name, system=data["system"], user_template=data["user_template"])
