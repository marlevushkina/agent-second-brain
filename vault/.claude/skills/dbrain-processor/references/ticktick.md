# TickTick Integration

<!--
╔══════════════════════════════════════════════════════════════════╗
║  КАК НАСТРОИТЬ ЭТОТ ФАЙЛ                                         ║
╠══════════════════════════════════════════════════════════════════╣
║  1. Замените [Your Clients] на имена ваших клиентов              ║
║  2. Замените [Your Company] на название вашей компании           ║
║  3. Замените [@your_channel] на ваш Telegram-канал               ║
║  4. Измените примеры задач на релевантные для вас                ║
║  5. Удалите этот комментарий после настройки                     ║
╚══════════════════════════════════════════════════════════════════╝
-->

## Available MCP Tools

### Reading Tasks
- `get_user_projects` — all projects list
- `get_project_with_data` — project with its tasks
- `get_task_by_ids` — get specific tasks by IDs

### Writing Tasks
- `create_task` — create new task
- `complete_task` — mark as done
- `update_task` — modify existing

---

## Pre-Creation Checklist

### 1. Check Workload (REQUIRED)

```
get_user_projects → get list of projects
get_project_with_data → get tasks for each relevant project
```

Build workload map from task due dates:
```
Mon: 2 tasks
Tue: 4 tasks  ← overloaded
Wed: 1 task
Thu: 3 tasks  ← at limit
Fri: 2 tasks
Sat: 0 tasks
Sun: 0 tasks
```

### 2. Check Duplicates (REQUIRED)

Review tasks in relevant project via `get_project_with_data`.

If similar exists → mark as duplicate, don't create.

---

## Priority by Domain

Based on user's work context (see [ABOUT.md](ABOUT.md)):

| Domain | Default Priority | Override |
|--------|-----------------|----------|
| Client Work | p1-p2 | — |
| Agency Ops (urgent) | p2 | — |
| Agency Ops (regular) | p3 | — |
| Content (with deadline) | p2-p3 | — |
| Product/R&D | p4 | масштабируемость → p3 |
| AI & Tech | p4 | автоматизация → p3 |

### Priority Keywords

| Keywords in text | Priority |
|-----------------|----------|
| срочно, критично, дедлайн клиента | p1 |
| важно, приоритет, до конца недели | p2 |
| нужно, надо, не забыть | p3 |
| (strategic, R&D, long-term) | p4 |

### TickTick Priority Mapping

TickTick uses numeric priorities (0-5, where 5 is highest):
| Our level | TickTick priority |
|-----------|------------------|
| p1 | 5 (highest) |
| p2 | 3 (high) |
| p3 | 1 (medium) |
| p4 | 0 (none/low) |

### Apply Decision Filters for Priority Boost

If entry matches 2+ filters → boost priority by 1 level:
- Это масштабируется?
- Это можно автоматизировать?
- Это усиливает экспертизу/бренд?
- Это приближает к продукту/SaaS?

---

## Date Mapping

| Context | Due date format |
|---------|----------------|
| **Client deadline** | exact date (YYYY-MM-DD) |
| **Urgent ops** | today / tomorrow |
| **This week** | friday date |
| **Next week** | next monday date |
| **Strategic/R&D** | +7 days |
| **Not specified** | tomorrow |

---

## Task Creation

```
create_task:
  title: "Task title"
  projectId: "..."     # from get_user_projects
  priority: 3          # TickTick priority (0-5)
  dueDate: "2026-02-15T00:00:00+0000"  # ISO format
```

### Task Title Style

User prefers: прямота, ясность, конкретика

<!-- Замените примеры на релевантные для вас -->
✅ Good:
- "Отправить презентацию клиенту"
- "Созвон с командой по проекту"
- "Написать пост про [тема]"

❌ Bad:
- "Подумать о презентации"
- "Что-то с клиентом"
- "Разобраться с AI"

### Workload Balancing

If target day has 3+ tasks:
1. Find next day with < 3 tasks
2. Use that day instead
3. Mention in report: "сдвинуто на {day} (перегрузка)"

---

## Project Detection

<!--
Настройте под свои проекты в TickTick.
Замените примеры клиентов и название канала.
-->

| Keywords | Project |
|----------|---------|
| [Your Client Names], клиент, бренд | Client Work |
| [Your Company], команда, найм, процессы | Company Ops |
| продукт, SaaS, MVP | Product |
| пост, [@your_channel], контент | Content |

If unclear → use Inbox (default project).

---

## Bulk Operations (overdue, reschedule, show all)

When user asks to move/show/list overdue tasks or tasks for a period:

**MANDATORY: scan ALL projects, not just one.**

```
Step 1: get_user_projects → save full list
Step 2: for EACH project → get_project_with_data(projectId)
Step 3: collect ALL tasks matching the filter (overdue, today, this week, etc.)
Step 4: perform the action on ALL matched tasks
Step 5: report results grouped by project
```

CRITICAL:
- Do NOT skip projects. If there are 8 projects, call get_project_with_data 8 times.
- A task is overdue if its dueDate < today AND status == 0 (not completed).
- When rescheduling, respect workload balancing (see above): max 3 tasks per day.
- Report must list EVERY moved/found task with its project name.

---

## Anti-Patterns (НЕ СОЗДАВАТЬ)

Based on user preferences:

- ❌ "Подумать о..." → конкретизируй действие
- ❌ "Разобраться с..." → что именно сделать?
- ❌ Абстрактные задачи без Next Action
- ❌ Дубликаты существующих задач
- ❌ Задачи без дат

---

## Error Handling

CRITICAL: Никогда не предлагай "добавить вручную".

If `create_task` fails:
1. Include EXACT error message in report
2. Continue with next entry
3. Don't mark as processed
4. User will see error and can debug

WRONG output:
  "Не удалось добавить (MCP недоступен). Добавь вручную: Task title"

CORRECT output:
  "Ошибка создания задачи: [exact error from MCP tool]"
