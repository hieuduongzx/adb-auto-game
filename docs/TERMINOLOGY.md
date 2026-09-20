# Product Terminology

This glossary is the source of truth for user-facing labels, messages, logs,
and documentation across Macro2k Hub, Designer, Runner, and DevScope.

| Preferred term | Use for | Avoid in user-facing text |
| --- | --- | --- |
| workflow | A complete automation definition | flow, macro |
| project | A workflow folder and its project settings | game, unless referring specifically to the game |
| game | The game represented by a project in Hub | app, title |
| activity | A selectable runnable unit in Runner | task, step |
| node | A graph item in Designer | block, task |
| function | A reusable graph in Designer | sub-workflow |
| Run | Execute a workflow from Hub or Runner | Start, except for the primary Runner button |
| Test run | Execute a workflow from Designer | Run, when describing Designer testing |
| Build | Package a standalone Runner executable | Export EXE |
| Export | Write a workflow to a new JSON file | Save as, when naming the action |
| Template | An image used for matching | crop, image, asset |
| Asset | A resource that is not specifically a matching template | file, image |
| Device | A connected Android device or emulator instance | target, when referring to the device |
| Target window | The selected Win32 window | device, for Win32 |
| Capture source | The source used to capture a screen frame | backend, in labels |
| Preview | The live or captured visual view | mirror, scope |
| Log | Timestamped runtime messages | console, output |

## Style Rules

- Use English for all user-facing UI, logs, dialogs, and documentation.
- Use sentence case for labels, buttons, headings, and messages.
- Start button labels with a verb: `Run`, `Build`, `Open`, `Clear`.
- Use `workflow` consistently in user-facing text, even when the internal JSON
  key or function name remains `flow`.
- Use `node` for graph items and `activity` for runnable units.
- Keep status messages short, direct, and free of terminal punctuation unless
  the message contains multiple sentences.
