# Planfix Integration (Team Tasks)

## Routing: Planfix vs TickTick

| Context | Target |
|---------|--------|
| Task for SMMEKALKA team | Planfix |
| Task for C-GROWTH team | Planfix |
| Task for KLEVERS team | Planfix |
| Delegate to employee | Planfix |
| Shared team task | Planfix |
| Personal task | TickTick |
| Mentoring | TickTick |
| Unclear | TickTick (default) |

### Routing Keywords

**→ Planfix:** команда, сотрудник, делегировать, поручить, назначить, SMMEKALKA, СММЕКАЛКА, Сммекалка, C-Growth, СиГроу, KLEVERS, Клеврс, [employee names]

**→ TickTick:** лично, я, мне, менторство, ментор, personal

**Default:** TickTick (if unclear where task belongs)

---

## Available MCP Tools

### Reading
- `mcp__planfix__searchPlanfixTask` — search tasks by title (optional: templateId)
- `mcp__planfix__getTask` — get task details by ID
- `mcp__planfix__getChildTasks` — get subtasks (supports recursive)

### Writing
- `mcp__planfix__createTask` — create new task
- `mcp__planfix__createComment` — add comment to task

### Contacts
- `mcp__planfix__searchPlanfixContact` — search by name/phone/email/telegram
- `mcp__planfix__searchPlanfixCompany` — search companies

---

## Task Creation

```
mcp__planfix__createTask:
  title: "Task title"
  description: "Task description"
```

### Task Title Style

Same as TickTick — direct, clear, actionable:

- "Подготовить отчёт для клиента X"
- "Написать ТЗ на лендинг"
- "Согласовать контент-план с командой"

---

## Anti-Patterns

- Do NOT create duplicate tasks (search first)
- Do NOT create vague tasks ("разобраться с...")
- Do NOT put personal tasks in Planfix
- Do NOT put team tasks in TickTick

---

## Error Handling

Same as TickTick — never suggest "add manually".

If `createTask` fails:
1. Include EXACT error message in report
2. Continue with next entry
3. Show error in HTML report
