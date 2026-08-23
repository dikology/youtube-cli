# Issue tracker: Linear

Issues and specs for this repo live in Linear.

- **Workspace**: [dikology](https://linear.app/dikology)
- **Team**: Dikology (`DIK`)
- **Project**: [youtube-cli](https://linear.app/dikology/project/youtube-cli-de7f3d9cf9d4)

Use the Linear MCP (or Linear API) for all operations. Do not use GitHub Issues for this repo.

## Conventions

- **Create an issue**: `save_issue` with `team: "Dikology"`, `project: "youtube-cli"`, `title`, and `description` (Markdown). New work starts in **Backlog** unless a skill specifies another state.
- **Read an issue**: `get_issue` with the identifier (e.g. `DIK-123`), including comments when the skill needs discussion.
- **List issues**: `list_issues` scoped to team Dikology and project youtube-cli, with state/label filters as needed.
- **Comment**: `save_comment` on the issue.
- **Apply / remove labels**: update the issue's `labels` via `save_issue`. Label sets replace the full list — include every label that should remain.
- **Close / cancel**: set state to **Done**, **Canceled**, or **Duplicate** as appropriate.

Issue identifiers use the `DIK-` prefix.

## Statuses

| State        | Type       | Use                                      |
| ------------ | ---------- | ---------------------------------------- |
| Backlog      | backlog    | Captured, not yet scheduled              |
| Todo         | unstarted  | Ready to start                           |
| In Progress  | started    | Actively being worked                    |
| In Review    | started    | Awaiting review                          |
| Done         | completed  | Finished                                 |
| Canceled     | canceled   | Will not be done                         |
| Duplicate    | duplicate  | Same as another issue                    |

Type labels already in the team (`Bug`, `Feature`, `Improvement`) are orthogonal to triage labels. Apply both when both apply.

## When a skill says "publish to the issue tracker"

Create a Linear issue on team Dikology, project youtube-cli.

## When a skill says "fetch the relevant ticket"

Load the Linear issue by identifier (`DIK-n`) including comments.
