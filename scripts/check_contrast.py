"""Check WCAG contrast of the current design text and interactive tokens."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "frontend" / "src" / "design-v2.css"

PAIRS = {
    "Основной текст на фоне": ("ink", "page"),
    "Текст карточки": ("ink", "paper"),
    "Вторичный текст на подложке": ("muted", "surface-muted"),
    "Вторичный текст на фоне": ("muted", "page"),
    "Вторичный текст в карточке": ("muted", "paper"),
    "Вторичный текст в плашке": ("muted", "soft"),
    "Основная кнопка": ("on-accent", "accent"),
    "Текст кнопки на тепловой карте": ("on-accent", "accent"),
    "Ссылка на фоне": ("link", "page"),
    "Ссылка в карточке": ("link", "paper"),
    "Активная вкладка": ("link", "soft"),
    "Ошибка": ("error", "error-bg"),
    "Свободна": ("free-ink", "free"),
    "Скоро занята": ("soon-ink", "soon"),
    "Занята, подпись на полосе штриховки": ("ink", "hatch"),
    "Занята или неизвестно, подпись на фоне": ("ink", "unknown"),
}


def luminance(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def contrast(fg, bg):
    darker, lighter = sorted((luminance(fg), luminance(bg)))
    return (lighter + .05) / (darker + .05)


def tokens(declaration):
    return dict(re.findall(r"--([a-z-]+):\s*(#[a-fA-F0-9]{6})\b", declaration))


def main():
    css = CSS.read_text(encoding="utf-8-sig")
    light = tokens(re.search(r":root\s*\{([^}]+)", css)[1])
    dark = light | tokens(re.search(r':root\[data-theme="dark"\]\s*\{([^}]+)', css)[1])
    system_dark = tokens(re.search(r':root:not\(\[data-theme="light"\]\)\s*\{([^}]+)', css)[1])
    if dark != light | system_dark:
        raise SystemExit("Dark theme overrides differ between explicit and system modes.")

    print("| Пара | Светлая | Тёмная |")
    print("| --- | ---: | ---: |")
    failures = []
    for label, (fg, bg) in PAIRS.items():
        ratios = [contrast(theme[fg], theme[bg]) for theme in (light, dark)]
        print(f"| {label} | {ratios[0]:.2f}:1 | {ratios[1]:.2f}:1 |")
        if min(ratios) < 4.5:
            failures.append(label)
    if failures:
        raise SystemExit("Below 4.5:1: " + ", ".join(failures))


if __name__ == "__main__":
    main()
