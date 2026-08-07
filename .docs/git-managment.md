# Git Management — Управление версиями проекта

Документирует git workflow, версионирование и правила работы с репозиторием Venus.

---

## Содержание

1. [Репозиторий и ветки](#репозиторий-и-ветки)
2. [Версионирование](#версионирование)
3. [Branching Strategy](#branching-strategy)
4. [Commit Guidelines](#commit-guidelines)
5. [Release Process](#release-process)
6. [Documentation Sync](#documentation-sync)

---

## Репозиторий и ветки

**URL:** https://github.com/psewdon1m-friday/chronos.git

### Основные ветки

| Ветка | Назначение | Защита | CI/CD |
|-------|------------|--------|-------|
| **dev** (default) | Основная разработка | Нет | Lint, test, build |
| **stage** | Предпродакшн тестирование | PR review | +Интеграционные тесты, stage deploy |
| **prod** | Продакшн | Multiple approvals | +Security scans, production deploy |

### Временные ветки
- `feature/*` — новые фичи (от dev)
- `bugfix/*` — исправления багов (от dev/stage)
- `hotfix/*` — срочные фиксы (от prod)

**Особенности:** Тэги доступны во всех ветках, но деплой происходит только из соответствующих веток.

### .gitignore стратегия

Единый файл с условными правилами:
- **Dev:** Включает dev-инструменты, логи, кэш
- **Stage/Prod:** Автоочистка через git hooks, только продакшн-ready файлы

**Всегда исключать:** `.env*`, `secrets/`, `*.log`

---

## Версионирование

### Semantic Versioning

Используем [SemVer 2.0.0](https://semver.org/):
- **MAJOR:** Breaking changes
- **MINOR:** Новая функциональность (backward-compatible)
- **PATCH:** Bug fixes (backward-compatible)

**Формат:** `vMAJOR.MINOR.PATCH` (пример: `v1.2.3`)

### Определение версии

```bash
# Проверить текущую версию
git describe --tags --abbrev=0

# Следующая версия:
# v1.2.5 → v1.2.6 (patch)
# v1.2.5 → v1.3.0 (minor)
# v1.2.5 → v2.0.0 (major)
```

### Обновление версии

**Workflow по веткам:**

**Dev ветка:**
1. Реализовать фичи в dev
2. Push в dev (CI/CD тестирование)
3. Создать tag при достижении milestones
4. Обновить `docs/versions.md`

**Stage ветка:**
1. Merge стабильной версии из dev в stage
2. Провести интеграционное тестирование
3. Создать stage tag (v1.2.3-stage.1)
4. Deploy на stage environment

**Prod ветка:**
1. Финальное тестирование на stage
2. Merge в prod ветку
3. Создать production tag (v1.2.3)
4. Manual deploy на production

### Формат обновления versions.md

```
v{MAJOR}.{MINOR}.{PATCH} ({branch}) ({YYYY-MM-DD} {HH:MM}): {краткое описание}
```

**Правила:**
- Новые версии добавляются сверху
- Обязательно указывать ветку: `(dev)`, `(stage)`, `(prod)`
- Формат даты: YYYY-MM-DD HH:MM

**Примеры:**
```
v1.3.0 (dev) (2025-11-25 16:30): persona management system
v1.2.6 (prod) (2025-11-23 10:00): production deployment
```

---


## Branching Strategy

### Feature Branches
- **Naming:** `feature/KT{N}-{description}` (пример: `feature/KT1-auth-system`)
- **Workflow:** Create от dev → develop → PR to dev → merge

### Bugfix Branches
- **Naming:** `bugfix/{issue-number}-{description}` (пример: `bugfix/42-fix-upload`)
- **Workflow:** Create от dev/stage → fix → PR to dev

### Hotfix Branches
- **Naming:** `hotfix/v{version}-{description}` (пример: `hotfix/v1.2.6-critical-bug`)
- **Workflow:** Create от prod → fix → merge to prod → cherry-pick to dev

---

## Commit Guidelines

### Формат commit message

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`

**Scopes:** `auth`, `projects`, `personas`, `media`, `cv`, `frontend`, `api`, `db`

**Примеры:**
```
feat(projects): add drag-and-drop placeholder reordering
fix(media): increase upload timeout for large files
docs(api): update API usage examples
```

**Проверка:** Pre-commit hooks с commitlint автоматически проверяют формат.

---

## Release Process

### Pre-release Checklist по веткам

**Для dev релиза:**
- [ ] Feature полностью реализована и протестирована
- [ ] Локальные тесты проходят
- [ ] Код соответствует code style
- [ ] [`docs/versions.md`](versions.md) updated с `(dev)`

**Для stage релиза:**
- [ ] Стабильная версия из dev
- [ ] Интеграционные тесты пройдены
- [ ] QA approval получен
- [ ] [`docs/versions.md`](versions.md) updated с `(stage)`
- [ ] Stage environment готов

**Для prod релиза:**
- [ ] Stage testing завершено успешно
- [ ] Все acceptance criteria выполнены
- [ ] Performance и security checks пройдены
- [ ] [`docs/versions.md`](versions.md) updated с `(prod)`
- [ ] Rollback plan подготовлен

---

### Release Steps по веткам

**Dev Release:**
```bash
# В dev ветке
git checkout dev
git pull origin dev

# Обновить versions.md
echo "v1.2.6 (dev) (2025-11-20 15:30): feature description" >> docs/versions.md

# Commit и push
git add docs/versions.md
git commit -m "docs: update versions.md for v1.2.6 dev release"
git push origin dev

# Создать tag
git tag -a v1.2.6-dev -m "Dev release v1.2.6"
git push origin v1.2.6-dev
```

**Stage Release:**
```bash
# Создать stage ветку от dev
git checkout dev
git pull origin dev
git checkout -b stage
git push origin stage

# Обновить versions.md для stage
echo "v1.2.6-stage.1 (stage) (2025-11-21 10:00): stage testing" >> docs/versions.md

# Commit и tag
git add docs/versions.md
git commit -m "docs: prepare v1.2.6 for stage testing"
git tag -a v1.2.6-stage.1 -m "Stage release v1.2.6-stage.1"
git push origin stage
git push origin v1.2.6-stage.1
```

**Prod Release:**
```bash
# Создать prod ветку от stage
git checkout stage
git pull origin stage
git checkout -b prod
git push origin prod

# Финальное обновление versions.md
echo "v1.2.6 (prod) (2025-11-22 14:00): production release" >> docs/versions.md

# Commit и tag
git add docs/versions.md
git commit -m "docs: production release v1.2.6"
git tag -a v1.2.6 -m "Production release v1.2.6"
git push origin prod
git push origin v1.2.6
```

---

### GitHub Releases

**Для production релизов:**
- Перейти в GitHub → Releases → New Release
- Select tag: v1.2.6
- Title: "Venus v1.2.6 - Production Release"
- Publish release

**Post-release monitoring:**
- Verify production deployment successful
- Monitor error rates и performance metrics
- Rollback готовность (stage ветка)

---

## Documentation Sync

### Какие файлы синхронизировать

**При каждом tag push:**
- [`docs/versions.md`](versions.md) — обязательно с указанием ветки

**При значительных изменениях:**
- [`docs/api_usage.md`](api_usage.md) — если API изменилось
- [`docs/directory_tree.md`](directory_tree.md) — если структура изменилась
- [`docs/project_passport.md`](project_passport.md) — при milestones

**При достижении контрольных точек:**
- [`docs/project_passport.md`](project_passport.md) — статус проекта
- [`docs/traceability-matrix.md`](traceability-matrix.md) — прогресс требований
- [`docs/stages.md`](stages.md) — если изменился план

**CHANGELOG.md ведется отдельно:**
- Обновляется в процессе работы
- Содержит детальную историю изменений
- Не требует синхронизации с git tags

---


---


## Troubleshooting

**Забыли обновить versions.md:**
```bash
echo "v1.2.6 (dev) (2025-11-20 15:30): description" >> docs/versions.md
git add docs/versions.md && git commit --amend --no-edit
```

**Неправильная версия tag:**
```bash
git tag -d v1.2.6 && git push origin :refs/tags/v1.2.6
git tag -a v1.2.7 -m "Correct version" && git push origin v1.2.7
```

**Committed секретные файлы:**
```bash
git rm --cached .env && git commit -m "chore: remove .env from git"
```

---

## Best Practices

- **Атомарные commits:** Один commit = одна логическая единица изменений
- **Частые commits:** Commit рано и часто для лучшей traceability
- **Pull before push:** Всегда синхронизируйтесь перед push
- **Review changes:** Просматривайте `git diff --staged` перед commit

---

## Связь с CI/CD

Git operations триггерят CI/CD pipeline по веткам:

**Dev ветка:**
- Push: автоматический CI (lint, test, build)
- Tag: создание dev release, обновление versions.md

**Stage ветка:**
- Push: CI + интеграционные тесты
- Tag: deploy на stage environment
- PR review: обязательно перед merge

**Prod ветка:**
- Push: финальный CI + security scans
- Tag: production deployment (manual approval)
- Releases: создание GitHub releases

**Детали:** См. [`docs/ci-cd-pipeline.md`](ci-cd-pipeline.md)

---

## Восстановление и откаты

### Откат к предыдущей версии

```bash
# Откатить working directory к тегу
git checkout v1.2.5

# Создать branch от этой версии
git checkout -b hotfix/rollback-v1.2.5

# Или hard reset (ОСТОРОЖНО!)
git reset --hard v1.2.5
```

### Откат к конкретному commit

```bash
# Найти commit hash
git log --oneline

# Soft reset (сохранить changes как uncommitted)
git reset --soft abc123

# Hard reset (удалить все changes)
git reset --hard abc123  # ОСТОРОЖНО!
```

---
