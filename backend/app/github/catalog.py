"""What GitHub data means as skills. Everything here is a fixed table or a parser: no LLM, so the
same repos always produce the same proposals and every proposal can point at the file or language
count it came from."""

import json
import re
import tomllib
from collections.abc import Callable

# A language must make up at least this many bytes of a repo to count as evidence of using it.
# A few hundred bytes is a config file or a stray script, not a skill.
MIN_LANGUAGE_BYTES = 5_000

NOTEBOOK_LANGUAGE = "Jupyter Notebook"

# GitHub language name -> the skill it evidences. Anything GitHub reports that isn't here
# (Dockerfile, Makefile, Batchfile, ...) is a file type rather than a skill and is not proposed.
LANGUAGE_SKILLS: dict[str, str] = {
    "Python": "Python",
    "JavaScript": "JavaScript",
    "TypeScript": "TypeScript",
    "HTML": "HTML",
    "CSS": "CSS",
    "SCSS": "Sass",
    "Java": "Java",
    "C": "C",
    "C++": "C++",
    "C#": "C#",
    "Go": "Go",
    "Rust": "Rust",
    "Kotlin": "Kotlin",
    "Swift": "Swift",
    "PHP": "PHP",
    "Ruby": "Ruby",
    "Dart": "Dart",
    "R": "R",
    "MATLAB": "MATLAB",
    "Shell": "Shell scripting",
    "Vue": "Vue",
    "Svelte": "Svelte",
    NOTEBOOK_LANGUAGE: "Jupyter Notebooks",
}

# Python package (lower-case, "-" for "_" and ".") -> skill.
PYTHON_PACKAGES: dict[str, str] = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "pytest": "pytest",
    "celery": "Celery",
    "redis": "Redis",
    "asyncpg": "PostgreSQL",
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "pymongo": "MongoDB",
    "motor": "MongoDB",
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "tensorflow-cpu": "TensorFlow",
    "keras": "Keras",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "pandas": "pandas",
    "numpy": "NumPy",
    "matplotlib": "Matplotlib",
    "opencv-python": "OpenCV",
    "opencv-python-headless": "OpenCV",
    "opencv-contrib-python": "OpenCV",
    "transformers": "Hugging Face Transformers",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "streamlit": "Streamlit",
    "gradio": "Gradio",
    "beautifulsoup4": "Beautiful Soup",
    "bs4": "Beautiful Soup",
    "selenium": "Selenium",
    "playwright": "Playwright",
}

# npm package (lower-case) -> skill.
NPM_PACKAGES: dict[str, str] = {
    "react": "React",
    "react-dom": "React",
    "react-native": "React Native",
    "next": "Next.js",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "svelte": "Svelte",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "typescript": "TypeScript",
    "tailwindcss": "Tailwind CSS",
    "vite": "Vite",
    "jest": "Jest",
    "vitest": "Vitest",
    "playwright": "Playwright",
    "@playwright/test": "Playwright",
    "three": "Three.js",
    "@tanstack/react-query": "TanStack Query",
    "zustand": "Zustand",
    "framer-motion": "Framer Motion",
    "prisma": "Prisma",
    "@prisma/client": "Prisma",
    "mongoose": "Mongoose",
    "socket.io": "Socket.IO",
    "redux": "Redux",
    "@reduxjs/toolkit": "Redux",
    "electron": "Electron",
}

# Root-level file name (lower-case) -> skill it evidences.
ROOT_FILE_SKILLS: dict[str, str] = {
    "dockerfile": "Docker",
    "docker-compose.yml": "Docker",
    "docker-compose.yaml": "Docker",
    "compose.yml": "Docker",
    "compose.yaml": "Docker",
}


def normalize_python_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def parse_requirements(text: str) -> list[str]:
    """Package names from a requirements.txt. Comments, options (-r, -e, --hash), bare URLs and
    blank lines are skipped; versions, extras, markers and environment conditions are stripped."""
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or re.match(r"(git\+|https?:|file:)", line):
            continue
        name = re.split(r"[\s=<>!~;\[@(,]", line, maxsplit=1)[0]
        if name:
            names.append(normalize_python_package(name))
    return names


def _requirement_name(spec: str) -> str:
    return normalize_python_package(re.split(r"[\s=<>!~;\[@(,]", spec.strip(), maxsplit=1)[0])


def parse_pyproject(text: str) -> list[str]:
    """Dependency names from pyproject.toml: PEP 621 `project.dependencies`, its optional
    groups, PEP 735 dependency groups, and Poetry's `tool.poetry.dependencies`."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    specs: list[str] = []
    project = data.get("project") or {}
    specs.extend(s for s in project.get("dependencies") or [] if isinstance(s, str))
    for group in (project.get("optional-dependencies") or {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    for group in (data.get("dependency-groups") or {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    names = [_requirement_name(s) for s in specs]
    poetry = (data.get("tool") or {}).get("poetry") or {}
    for section in ("dependencies", "dev-dependencies"):
        names.extend(normalize_python_package(k) for k in (poetry.get(section) or {}))
    for group in (poetry.get("group") or {}).values():
        names.extend(normalize_python_package(k) for k in (group.get("dependencies") or {}))
    return [n for n in names if n and n != "python"]


def parse_package_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        block = data.get(section)
        if isinstance(block, dict):
            names.extend(str(key).lower() for key in block)
    return names


def is_manifest(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered in ("pyproject.toml", "package.json")
        or re.fullmatch(r"requirements[\w.-]*\.txt", lowered) is not None
    )


def dependency_skills(filename: str, text: str) -> list[str]:
    """The distinct skills a manifest's dependencies evidence, in first-seen order."""
    lowered = filename.lower()
    if lowered == "package.json":
        names, table = parse_package_json(text), NPM_PACKAGES
    elif lowered == "pyproject.toml":
        names, table = parse_pyproject(text), PYTHON_PACKAGES
    elif is_manifest(lowered):
        names, table = parse_requirements(text), PYTHON_PACKAGES
    else:
        return []
    skills: list[str] = []
    for name in names:
        skill = table.get(name)
        if skill and skill not in skills:
            skills.append(skill)
    return skills


ManifestParser = Callable[[str], list[str]]
