# Do `styre check`'s warnings predict trouble?

102 phases from 19 design versions, scored two ways:

- **Went badly**: stopped for a design reason, or needed a fresh start for context. Base rate 50/102 (49%).
- **Stopped**: stopped for a design reason, uncommitted. Base rate 15/102 (15%).

A warning is useful when its precision beats the base rate. Precision: of the phases it flagged, how many went that way. Recall: of the phases that went that way, how many it flagged.

| Warning | Flagged | Went badly: precision | recall | Stopped: precision | recall |
| --- | --- | --- | --- | --- | --- |
| preamble names documents | 11 | 4/11 (36%) | 4/50 (8%) | 4/11 (36%) | 4/15 (27%) |
| asks for a skipped test | 1 | 0/1 (0%) | 0/50 (0%) | 0/1 (0%) | 0/15 (0%) |
| names a document | 2 | 0/2 (0%) | 0/50 (0%) | 0/2 (0%) | 0/15 (0%) |
| large phase | 5 | 0/5 (0%) | 0/50 (0%) | 0/5 (0%) | 0/15 (0%) |
| two toolchains | 49 | 36/49 (73%) | 36/50 (72%) | 10/49 (20%) | 10/15 (67%) |
| new library, no example | 16 | 5/16 (31%) | 5/50 (10%) | 4/16 (25%) | 4/15 (27%) |
| any warning | 68 | 40/68 (59%) | 40/50 (80%) | 14/68 (21%) | 14/15 (93%) |

Peak context per phase: median 83,271, max 130,901 tokens.

## Phases

| Design | Phase | Went badly | Stopped | Peak context | Flagged as |
| --- | --- | --- | --- | --- | --- |
| `agent-todo.md` | 1 |  |  | 55,903 | new library, no example, preamble names documents |
| `agent-todo.md` | 2 | yes | yes | 93,790 | new library, no example, preamble names documents |
| `agent-todo.md` | 3 | yes | yes | 40,055 | preamble names documents |
| `agent-todo.md` | 4 | yes | yes | 38,681 | new library, no example, preamble names documents |
| `agent-todo.md` | 5 | yes | yes | 54,969 | preamble names documents |
| `agent-todo.md` | 6 |  |  | 66,220 | preamble names documents |
| `agent-todo.md` | 7 |  |  | 22,948 | new library, no example, preamble names documents |
| `agent-todo.md` | 8 |  |  | 60,359 | large phase, preamble names documents |
| `agent-todo.md` | 9 |  |  | 86,334 | preamble names documents |
| `agent-todo.md` | 10 |  |  | 44,766 | preamble names documents |
| `agent-todo.md` | 11 |  |  | 59,111 | asks for a skipped test, preamble names documents |
| `agent-todo.md` | 12 |  |  | 36,870 |  |
| `reminders-design.md` | 1 |  |  | 50,669 | large phase, new library, no example |
| `reminders-design.md` | 2 | yes | yes | 130,901 |  |
| `reminders-design.md` | 3 |  |  | 48,236 | large phase |
| `reminders-design.md` | 4 |  |  | 76,664 | large phase |
| `reminders-design.md` | 5 |  |  | 71,548 |  |
| `reminders-design.md` | 6 |  |  | 95,914 |  |
| `reminders-design.md` | 7 |  |  | 92,806 |  |
| `todo-rules-design.md` | 1 |  |  | 27,721 |  |
| `todo-rules-design.md` | 2 |  |  | 19,378 |  |
| `todo-rules-design.md` | 3 |  |  | 14,404 |  |
| `todo-rules-design.md` | 4 |  |  | 20,781 | new library, no example |
| `todo-rules-design.md` | 5 |  |  | 9,999 |  |
| `reactions-design.md` | 1 |  |  | 23,048 |  |
| `reactions-design.md` | 2 |  |  | 31,519 |  |
| `reactions-design.md` | 3 |  |  | 21,930 |  |
| `reactions-design.md` | 4 |  |  | 66,360 |  |
| `reactions-design.md` | 5 |  |  | 38,746 |  |
| `reactions-design.md` | 6 |  |  | 40,631 |  |
| `reactions-design.md` | 7 |  |  | 45,018 |  |
| `reactions-design.md` | 8 |  |  | 60,152 |  |
| `web-design.md` | 1 |  |  | 36,510 |  |
| `web-design.md` | 2 |  |  | 31,187 |  |
| `web-design.md` | 3 |  |  | 28,267 |  |
| `web-design.md` | 4 |  |  | 37,743 |  |
| `web-tanstack-design.md` | 1 |  |  | 53,736 | new library, no example |
| `web-tanstack-design.md` | 2 |  |  | 47,174 | new library, no example |
| `web-tanstack-design.md` | 3 |  |  | 46,670 | two toolchains |
| `web-tanstack-design.md` | 4 |  |  | 73,923 | two toolchains |
| `web-tanstack-design.md` | 5 |  |  | 75,701 | two toolchains |
| `web-edit-design.md` | 1 |  |  | 104,079 | large phase, two toolchains |
| `web-edit-design.md` | 2 | yes | yes | 90,176 | new library, no example, two toolchains |
| `web-edit-design.md` | 3 |  |  | 115,801 | names a document, new library, no example, two toolchains |
| `sources-design.md` | 3 | yes | yes | 74,642 | new library, no example, two toolchains |
| `sources-design.md` | 4 | yes |  | 74,009 | two toolchains |
| `sources-design.md` | 5 | yes |  | 73,805 | two toolchains |
| `sources-design.md` | 6 | yes |  | 95,274 | two toolchains |
| `sources-design.md` | 7 | yes |  | 87,646 |  |
| `today-design.md` | 1 | yes |  | 91,837 |  |
| `today-design.md` | 2 | yes |  | 94,619 | two toolchains |
| `today-design.md` | 3 |  |  | 77,649 | two toolchains |
| `today-design.md` | 4 |  |  | 68,321 |  |
| `today-design.md` | 5 |  |  | 67,348 |  |
| `today-design.md` | 6 |  |  | 86,720 | two toolchains |
| `today-design.md` | 7 | yes |  | 95,045 |  |
| `today-design.md` | 8 | yes |  | 91,533 | two toolchains |
| `split-design.md` | 1 | yes |  | 91,364 | new library, no example, two toolchains |
| `split-design.md` | 2 |  |  | 72,743 | names a document, new library, no example |
| `search-design.md` | 1 |  |  | 84,106 | new library, no example, two toolchains |
| `search-design.md` | 2 |  |  | 83,271 | new library, no example |
| `search-design.md` | 3 | yes |  | 92,521 |  |
| `search-design.md` | 4 | yes |  | 91,831 | two toolchains |
| `notes-design.md` | 1 |  |  | 66,275 |  |
| `notes-design.md` | 2 |  |  | 47,986 |  |
| `notes-design.md` | 3 | yes |  | 91,399 | two toolchains |
| `notes-design.md` | 4 | yes |  | 92,761 | two toolchains |
| `ask-design.md` | 1 | yes |  | 91,946 |  |
| `ask-design.md` | 2 | yes |  | 92,526 | two toolchains |
| `ask-design.md` | 3 | yes |  | 96,301 |  |
| `ask-design.md` | 4 | yes |  | 92,798 |  |
| `ask-design.md` | 5 | yes |  | 92,403 | two toolchains |
| `ts-domain-design.md` | 1 |  |  | 58,800 | new library, no example, two toolchains |
| `ts-domain-design.md` | 2 | yes |  | 95,485 | two toolchains |
| `ts-domain-design.md` | 3 | yes |  | 94,292 | two toolchains |
| `ts-domain-design.md` | 4 | yes |  | 97,896 | two toolchains |
| `ts-domain-design.md` | 5 | yes | yes | 94,318 | two toolchains |
| `ts-core-design.md` | 1 | yes |  | 95,995 | two toolchains |
| `ts-core-design.md` | 2 | yes | yes | 94,284 | two toolchains |
| `ts-core-design.md` | 3 | yes | yes | 103,411 | two toolchains |
| `ts-core-design.md` | 4 | yes |  | 100,802 | two toolchains |
| `ts-core-design.md` | 5 |  |  | 77,502 | two toolchains |
| `ts-core-design.md` | 6 | yes | yes | 98,527 | two toolchains |
| `ts-core-design.md` | 7 | yes |  | 115,850 | two toolchains |
| `ts-core-design.md` | 8 |  |  | 75,732 | two toolchains |
| `ts-core-design.md` | 9 |  |  | 75,432 | two toolchains |
| `ts-core-design.md` | 10 | yes |  | 94,765 | two toolchains |
| `ts-core-design.md` | 11 | yes |  | 97,451 | two toolchains |
| `ts-core-design.md` | 12 | yes | yes | 104,300 | two toolchains |
| `ts-core-design.md` | 13 |  |  | 89,052 | two toolchains |
| `ts-core-design.md` | 14 | yes |  | 94,902 | two toolchains |
| `ts-core-design.md` | 15 | yes |  | 98,681 |  |
| `ts-core-design.md` | 16 | yes |  | 94,394 |  |
| `basics-design.md` | 1 | yes |  | 105,247 | two toolchains |
| `basics-design.md` | 3 | yes |  | 95,271 | two toolchains |
| `basics-design.md` | 4 | yes |  | 92,790 | two toolchains |
| `basics-design.md` | 5 | yes | yes | 24,222 | two toolchains |
| `basics-design.md` | 5 | yes |  | 92,693 | two toolchains |
| `basics-design.md` | 6 | yes | yes | 100,431 | two toolchains |
| `basics-design.md` | 7 | yes |  | 91,741 | two toolchains |
| `basics-design.md` | 8 | yes |  | 94,437 | two toolchains |
| `basics-design.md` | 9 | yes | yes | 41,753 | two toolchains |

## Runs left out

- `20260930-115135`: calendar-design.md not found in git history
- `20260930-165112`: today-design.md not found in git history

