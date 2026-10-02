---
kind: chronos-monthly-report
period: "{{chronos.month}}"
timezone: "{{chronos.timezone}}"
tags: [chronos, monthly-report]
---

# Chronos · {{chronos.month_title}}

> [!summary] Итог месяца
> **{{chronos.total}}** учтено за {{chronos.days}} календарных дней. Покрытие месяца — **{{chronos.coverage}}**.

**Период:** {{chronos.period}}  
**Часовой пояс:** `{{chronos.timezone}}`

## Распределение по категориям

{{chronos.category_chart}}

{{chronos.category_table}}

## Ритм по дням

{{chronos.daily_chart}}

{{chronos.daily_table}}

## Связь с веткой

@chronos_analytics

> [!note] Метод
> Доли категорий рассчитаны от учтённого времени. Покрытие рассчитано от полной длительности календарного месяца. Интервалы, пересекающие полночь, разделены по дням в указанном часовом поясе.
