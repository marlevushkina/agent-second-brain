#!/bin/bash
# Patch @alexarevalo.ai/mcp-server-ticktick v1.1.9
# Fixes: get_project_with_data Zod validation + update_task schema
#
# Run on VPS:  bash scripts/patch-ticktick-mcp.sh
# Revert:      npm install -g @alexarevalo.ai/mcp-server-ticktick@1.1.9

set -euo pipefail

MCP_DIR=$(dirname "$(readlink -f "$(which mcp-server-ticktick)")")/..
DIST="$MCP_DIR/dist"

if [ ! -f "$DIST/common/types.js" ]; then
    echo "ERROR: MCP package not found. Install first:"
    echo "  npm install -g @alexarevalo.ai/mcp-server-ticktick@1.1.9"
    exit 1
fi

echo "Patching TickTick MCP at: $DIST"
echo "Version: $(node -e "console.log(require('$MCP_DIR/package.json').version)")"

# Backup originals
for f in common/types.js operations/projects.js operations/tasks.js; do
    if [ ! -f "$DIST/$f.orig" ]; then
        cp "$DIST/$f" "$DIST/$f.orig"
        echo "  Backed up $f -> $f.orig"
    fi
done

# --- Patch 1: common/types.js ---
# Add .nullable() to optional string/array fields so null values from API pass validation
# Add .passthrough() to allow extra fields from API
cat > "$DIST/common/types.js" << 'TYPES_EOF'
import { z } from 'zod';
export const TickTickProjectSchema = z.object({
    id: z.string(),
    name: z.string(),
    color: z.string().optional().nullable(),
    sortOrder: z.number().optional().nullable(),
    kind: z.string().optional().nullable(),
    closed: z.boolean().optional().nullable(),
    groupId: z.string().optional().nullable(),
    viewMode: z.string().optional().nullable(),
    permission: z.string().optional().nullable(),
}).passthrough();
export const TickTickTaskSchema = z.object({
    id: z.string(),
    isAllDay: z.boolean().optional().nullable(),
    projectId: z.string(),
    title: z.string(),
    content: z.string().optional().nullable(),
    desc: z.string().optional().nullable(),
    timeZone: z.string().optional().nullable(),
    repeatFlag: z.string().optional().nullable(),
    startDate: z.string().optional().nullable(),
    dueDate: z.string().optional().nullable(),
    reminders: z.array(z.string()).optional().nullable(),
    priority: z.number().optional().nullable(),
    status: z.number(),
    completedTime: z.string().optional().nullable(),
    sortOrder: z.number().optional().nullable(),
    items: z
        .array(z.object({
        id: z.string(),
        status: z.number(),
        title: z.string(),
        sortOrder: z.number().optional().nullable(),
        startDate: z.string().optional().nullable(),
        isAllDay: z.boolean().optional().nullable(),
        timeZone: z.string().optional().nullable(),
        completedTime: z.string().optional().nullable(),
    }).passthrough())
        .optional()
        .nullable(),
}).passthrough();
export const TickTickCheckListItemSchema = z.object({
    title: z.string().describe('Subtask item title'),
    startDate: z
        .string()
        .optional()
        .nullable()
        .describe(`Subtask item start date in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
    isAllDay: z.boolean().optional().nullable().describe('Is all day subtask item'),
    sortOrder: z.number().optional().nullable().describe('Subtask item sort order'),
    timeZone: z
        .string()
        .optional()
        .nullable()
        .describe('Subtask item time zone. Example: "America/Los_Angeles"'),
    status: z
        .number()
        .optional()
        .nullable()
        .describe('The completion status of subtask. Normal: 0, Completed: 1'),
    completedTime: z
        .string()
        .optional()
        .nullable()
        .describe(`Subtask item completed time in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
});
TYPES_EOF
echo "  Patched common/types.js"

# --- Patch 2: operations/projects.js ---
# Make project/tasks optional with defaults, add .passthrough()
cat > "$DIST/operations/projects.js" << 'PROJECTS_EOF'
import { z } from 'zod';
import { getFormattedColor, ticktickRequest } from '../common/utils.js';
import { TICKTICK_API_URL } from '../common/urls.js';
import { TickTickProjectSchema, TickTickTaskSchema } from '../common/types.js';
export const GetUserProjectsResponseSchema = z.array(TickTickProjectSchema);
export const GetProjectWithDataResponseSchema = z.object({
    project: TickTickProjectSchema.optional().nullable(),
    tasks: z.array(TickTickTaskSchema).optional().nullable(),
    columns: z
        .array(z
        .object({
        id: z.string().optional(),
        projectId: z.string().optional(),
        name: z.string().optional(),
        sortOrder: z.number().optional(),
    })
        .passthrough()
        .optional())
        .optional()
        .nullable(),
}).passthrough();
export const ProjectIdOptionsSchema = z.object({
    projectId: z.string().describe('Project identifier'),
});
export const CreateProjectOptionsSchema = z.object({
    name: z.string().describe('Project name'),
    color: z.string().default('#4772FA').optional().describe('Project color'),
    viewMode: z
        .enum(['list', 'kanban', 'timeline'])
        .default('list')
        .optional()
        .describe('View mode'),
    kind: z
        .enum(['TASK', 'NOTE'])
        .default('TASK')
        .optional()
        .describe('Project kind'),
});
export const UpdateProjectOptionsSchema = z.object({
    projectId: z.string().describe('Project identifier'),
    name: z.string().optional().describe('Project name'),
    color: z.string().optional().describe('Project color'),
    sortOrder: z.number().optional().describe('Project sort order'),
    viewMode: z
        .enum(['list', 'kanban', 'timeline'])
        .optional()
        .describe('View mode'),
    kind: z.enum(['TASK', 'NOTE']).optional().describe('Project kind'),
});
export async function getUserProjects() {
    const response = await ticktickRequest(`${TICKTICK_API_URL}/project`);
    return GetUserProjectsResponseSchema.parse(response);
}
export async function getProjectById(projectId) {
    const response = await ticktickRequest(`${TICKTICK_API_URL}/project/${projectId}`);
    return TickTickProjectSchema.parse(response);
}
export async function getProjectWithData(projectId) {
    const response = await ticktickRequest(`${TICKTICK_API_URL}/project/${projectId}/data`);
    const parsed = GetProjectWithDataResponseSchema.parse(response);
    return {
        project: parsed.project || { id: projectId, name: 'Unknown' },
        tasks: parsed.tasks || [],
        columns: parsed.columns || [],
    };
}
export async function createProject(params) {
    const { color, ...rest } = params;
    const response = await ticktickRequest(`${TICKTICK_API_URL}/project`, {
        method: 'POST',
        body: {
            color: getFormattedColor(color),
            ...rest,
        },
    });
    return TickTickProjectSchema.parse(response);
}
export async function updateProject(params) {
    const { color, projectId, ...rest } = params;
    const response = await ticktickRequest(`${TICKTICK_API_URL}/project/${projectId}`, {
        method: 'POST',
        body: {
            color: color ? getFormattedColor(color) : undefined,
            ...rest,
        },
    });
    return TickTickProjectSchema.parse(response);
}
export async function deleteProject(projectId) {
    await ticktickRequest(`${TICKTICK_API_URL}/project/${projectId}`, {
        method: 'DELETE',
    });
}
PROJECTS_EOF
echo "  Patched operations/projects.js"

# --- Patch 3: operations/tasks.js ---
# Make 'id' optional in UpdateTaskOptionsSchema (Claude only needs taskId)
# Add .passthrough() to response parsing for resilience
cat > "$DIST/operations/tasks.js" << 'TASKS_EOF'
import { z } from 'zod';
import { ticktickRequest } from '../common/utils.js';
import { TickTickCheckListItemSchema, TickTickTaskSchema, } from '../common/types.js';
export const GetTaskByIdsOptionsSchema = z.object({
    projectId: z.string().describe('Project identifier'),
    taskId: z.string().describe('Task identifier'),
});
export const GetTaskByIdsResponseSchema = TickTickTaskSchema;
export const CreateTaskOptionsSchema = z.object({
    title: z.string().describe('Task title'),
    projectId: z.string().describe('Project id'),
    content: z.string().optional().describe('Task content'),
    desc: z.string().optional().describe('Task description'),
    isAllDay: z.boolean().optional().describe('Is all day task'),
    startDate: z
        .string()
        .optional()
        .describe(`Task start date in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
    dueDate: z
        .string()
        .optional()
        .describe(`Task due date in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
    timeZone: z
        .string()
        .optional()
        .describe('Task time zone. Example: "America/Los_Angeles"'),
    reminders: z
        .array(z.string())
        .optional()
        .describe('List of reminder triggers in iCalendar (RFC 5545) format. Example: ["TRIGGER:P0DT9H0M0S", "TRIGGER:PT0S"]'),
    repeatFlag: z
        .string()
        .optional()
        .describe('Task repeat flag in iCalendar (RFC 5545) format. Example: RRULE:FREQ=DAILY;INTERVAL=1'),
    priority: z
        .number()
        .optional()
        .describe('Task priority None: 0, Low: 1, Medium: 3, High: 5'),
    sortOrder: z.string().optional().describe('Task sort order. Example: 12345'),
    items: z
        .array(TickTickCheckListItemSchema)
        .optional()
        .describe('The list of subtasks'),
});
export const UpdateTaskOptionsSchema = z.object({
    taskId: z.string().describe('Task identifier'),
    id: z.string().optional().describe('Task identifier (body). Defaults to taskId if omitted.'),
    projectId: z.string().describe('Project id'),
    title: z.string().optional().describe('Task title'),
    content: z.string().optional().describe('Task content'),
    desc: z.string().optional().describe('Task description'),
    isAllDay: z.boolean().optional().describe('Is all day task'),
    startDate: z
        .string()
        .optional()
        .describe(`Task start date in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
    dueDate: z
        .string()
        .optional()
        .describe(`Task due date in "yyyy-MM-dd'T'HH:mm:ssZ" format`),
    timeZone: z
        .string()
        .optional()
        .describe('Task time zone. Example: "America/Los_Angeles"'),
    reminders: z
        .array(z.string())
        .optional()
        .describe('List of reminder triggers in iCalendar (RFC 5545) format. Example: ["TRIGGER:P0DT9H0M0S", "TRIGGER:PT0S"]'),
    repeatFlag: z
        .string()
        .optional()
        .describe('Task repeat flag in iCalendar (RFC 5545) format. Example: RRULE:FREQ=DAILY;INTERVAL=1'),
    priority: z
        .number()
        .optional()
        .describe('Task priority None: 0, Low: 1, Medium: 3, High: 5'),
    sortOrder: z.string().optional().describe('Task sort order. Example: 12345'),
    items: z
        .array(TickTickCheckListItemSchema)
        .optional()
        .describe('The list of subtasks'),
});
export const TasksIdsOptionsSchema = z.object({
    taskId: z.string().describe('Task identifier'),
    projectId: z.string().describe('Project identifier'),
});
export async function getTaskByIds(params) {
    const { projectId, taskId } = GetTaskByIdsOptionsSchema.parse(params);
    const url = `https://api.ticktick.com/open/v1/project/${projectId}/task/${taskId}`;
    const response = await ticktickRequest(url);
    return GetTaskByIdsResponseSchema.parse(response);
}
export async function createTask(params) {
    const url = `https://api.ticktick.com/open/v1/task`;
    const response = await ticktickRequest(url, {
        method: 'POST',
        body: {
            ...params,
        },
    });
    return TickTickTaskSchema.parse(response);
}
export async function updateTask(params) {
    const { taskId, id, ...rest } = params;
    const effectiveId = taskId || id;
    const url = `https://api.ticktick.com/open/v1/task/${effectiveId}`;
    const response = await ticktickRequest(url, {
        method: 'POST',
        body: {
            id: effectiveId,
            ...rest,
        },
    });
    return TickTickTaskSchema.parse(response);
}
export async function completeTask({ taskId, projectId, }) {
    const url = `https://api.ticktick.com/open/v1/project/${projectId}/task/${taskId}/complete`;
    await ticktickRequest(url, {
        method: 'POST',
    });
}
export async function deleteTask({ taskId, projectId, }) {
    const url = `https://api.ticktick.com/open/v1/project/${projectId}/task/${taskId}`;
    await ticktickRequest(url, {
        method: 'DELETE',
    });
}
TASKS_EOF
echo "  Patched operations/tasks.js"

echo ""
echo "Done! Restart the MCP server or bot to apply changes."
echo "  systemctl restart d-brain"
