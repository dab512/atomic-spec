"""Binary Cyrillic-presence checks for real annotation prose; no language inference or ratios."""

import re

# atomic-spec://ATOMIC-GUARD-001/DR-22
# Проверка ru учитывает всю кириллицу, включая расширенные символы: ограничение только русским алфавитом давало бы ложные отказы.
CYRILLIC = re.compile(r"[\u0400-\u052f\u1c80-\u1c8f\u2de0-\u2dff\ua640-\ua69f\U0001e030-\U0001e08f]")


# atomic-spec://ATOMIC-GUARD-001/DR-22
# Хотя бы один символ кириллицы означает ru; при отсутствии кириллицы выбираем en независимо от остального текста.
def detected(text):
    return "ru" if CYRILLIC.search(text) else "en"


# atomic-spec://ATOMIC-GUARD-001/DR-22
# Язык пояснения обязан соответствовать явной настройке, а в auto — алфавиту указанного требования; язык URI не влияет на результат.
def assess(comment, requirement, settings):
    expected = detected(requirement) if settings["language"] == "auto" else settings["language"]
    actual = detected(comment)
    return dict(
        status="pass" if actual == expected else "mismatch",
        expected_language=expected,
        actual_language=actual,
    )
