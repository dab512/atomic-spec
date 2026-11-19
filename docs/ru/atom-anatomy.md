[English](../atom-anatomy.md) | Русский

# Анатомия атома

[Бизнес-шаблон](../../templates/atom-template.spec.md) и
[архитектурный шаблон](../../templates/architecture-template.spec.md) имеют разное назначение.

Метаданные: устойчивые `id`, `type`, `parent`, `title`, `status`, `change_class`,
необязательный `change_type`, акторы/события, владельцы и даты. Иерархия:
system → domain → aggregate/use-case → scenario. Используйте уровни своего проекта;
пустые промежуточные атомы не нужны. Именование и пути определяет проект.

## Бизнес-атом

Intent; Domain Rules; Acceptance Criteria; Business Model; Constraints;
Open Questions; Decision Log. Здесь остаются понятия, события и инварианты бизнеса.
Обязательные измеримые гарантии получают устойчивые DR/BR-ID для прямой трассировки.
Таблицы решений полезны для комбинаций условий; они не обязательная формальность.

Правило объявляется вне code fence. AC — отдельный заголовок со следующим Gherkin:

```markdown
### AC-1. Повтор оплаты

Проверяет DR-1.

~~~gherkin
Scenario: Нет повторного списания
  Given оплата уже завершена
  When повторяется та же оплата
  Then общая списанная сумма не меняется
~~~
```

## Архитектурный атом

Intent; Requirements Served; Domain Rules; Acceptance Criteria; Contracts;
Alternatives and Replacement; Open Questions; Decision Log. Допустимы API, схемы,
транзакции и технологии. `satisfies` и Requirements Served выражают связи с бизнесом;
их смысл проверяется вручную. Guard автоматически не валидирует этот граф frontmatter.

Код тестов, матрицы/протоколы прогонов и карта файлов находятся рядом с выбранной
реализацией. Бизнес-атом сохраняет пригодность для другого стека.


[Методология](methodology.md) · [Gates](gate-validation.md) · [Миграция 2.0](migration-v2.md)
