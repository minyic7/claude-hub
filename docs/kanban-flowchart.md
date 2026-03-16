# Kanban System — Complete Flowchart

## 1. Ticket Lifecycle (State Machine)

```mermaid
stateDiagram-v2
    [*] --> TODO: POST /tickets (create)

    TODO --> QUEUED: bulk-start\n(max_sessions reached)
    TODO --> IN_PROGRESS: POST /start

    QUEUED --> IN_PROGRESS: process_queue()\nauto-dequeue
    QUEUED --> TODO: DELETE /queue/{id}\nor dequeue

    IN_PROGRESS --> BLOCKED: TicketAgent\nescalate tool
    IN_PROGRESS --> VERIFYING: session ends\n(tmux dead)
    IN_PROGRESS --> FAILED: stop / error / timeout
    IN_PROGRESS --> TODO: rollback\n(session start failed)

    BLOCKED --> IN_PROGRESS: POST /answer\nor /message
    BLOCKED --> FAILED: timeout / error

    VERIFYING --> REVIEWING: agent review\nenabled
    VERIFYING --> AWAITING_MERGE: agent disabled\n+ verify passed
    VERIFYING --> FAILED: verify failed\n(no commits / no PR)

    REVIEWING --> AWAITING_MERGE: agent approves
    REVIEWING --> IN_PROGRESS: agent rejects\n→ respawn session
    REVIEWING --> FAILED: 3x rejected\nor respawn failed

    AWAITING_MERGE --> IN_PROGRESS: request-changes\nor resolve-conflicts
    AWAITING_MERGE --> MERGING: POST /merge\n(CI pending)
    AWAITING_MERGE --> MERGED: POST /merge\n(CI passed)
    AWAITING_MERGE --> TODO: POST /revert

    MERGING --> MERGED: CI passes\n→ auto-merge
    MERGING --> FAILED: CI fails\nor timeout (10min)
    MERGING --> AWAITING_MERGE: server restart\n(recovery)

    FAILED --> IN_PROGRESS: POST /retry
    FAILED --> AWAITING_MERGE: POST /mark-review
    FAILED --> TODO: POST /revert

    MERGED --> [*]
```

## 2. Start Ticket — Full Flow

```mermaid
flowchart TD
    A["POST /tickets/{id}/start"] --> B{depends_on\nall merged?}
    B -- No --> B1[HTTP 400\nDependency not met]
    B -- Yes --> C{stale tmux\nsession?}
    C -- Yes --> C1[cleanup_session]
    C1 --> D
    C -- No --> D{active_count\n>= max_sessions?}
    D -- Yes --> D1[HTTP 429\nMax sessions reached]
    D -- No --> E{total_count\n> max_total?}
    E -- Yes --> E1[evict_idle_sessions\nkill oldest idle]
    E1 --> F
    E -- No --> F

    F[ensure_reference\nbare clone] --> G[clone_for_ticket\nper-ticket clone]
    G -- fail --> G1[HTTP 500\nClone failed]
    G -- ok --> H["transition TODO → IN_PROGRESS\nset started_at"]

    H --> I["Build task prompt:\ndescription + branch info\n+ push verification"]
    I --> J["session_manager.start_session()\ntmux new-session\nclaude -p task --stream-json\n--dangerously-skip-permissions"]
    J -- fail --> J1["rollback → TODO\ncleanup_session"]
    J -- ok --> K["save tmux_session name\nbroadcast ticket_updated"]
    K --> L["asyncio.create_task(\n_tail_and_broadcast)"]
    L --> M{agent enabled\n+ API key?}
    M -- Yes --> N["TicketAgent.run(log_path)\nReAct supervision loop"]
    M -- No --> O["Simple mode:\ntail_log → broadcast activity"]
```

## 3. TicketAgent ReAct Loop

```mermaid
flowchart TD
    A["TicketAgent.run(log_path)"] --> B["tail_log() async generator"]
    B --> C{new event?}
    C -- Yes --> D[append to activity\nbroadcast to WebSocket]
    D --> E[buffer event]
    E --> F{is_critical OR\nbuffer >= batch_size?}
    F -- No --> C
    F -- Yes --> G["_process_batch(buffer)"]

    G --> H["Summarize events → user message\nAppend to messages history\nTrim to max_context_messages"]
    H --> I["_call_api()"]
    I --> J{budget check\ncan_spend?}
    J -- No --> J1["Broadcast warning:\nBudget exceeded\nStop API calls"]
    J -- Yes --> K["LLM API call\n(Anthropic or OpenAI)"]
    K --> L["record_spend()\nupdate cost counters"]
    L --> M{response type?}

    M -- text --> N["Record activity:\ncommentary"]
    M -- tool_use --> O{which tool?}

    O -- tmux_send --> P["Send text to\nClaude Code session\n(intervention)"]
    O -- file_read --> Q["Read file from\nclone_path"]
    O -- git_status --> R["git status --short"]
    O -- escalate --> S["transition → BLOCKED\nset blocked_question\nbroadcast escalation"]
    O -- pause_session --> T["Send Ctrl+C\nemergency stop"]
    O -- wait --> U["No action\ncontinue monitoring"]
    O -- web_search --> V["Search web\nreturn summary"]

    P & Q & R & S & T & U & V --> W[tool_result → messages]
    W --> X{stop_reason\n== tool_use?}
    X -- Yes --> I
    X -- No --> C

    C -- session ends --> Y["Final batch processing"]
    Y --> Z["cleanup_session()\n_verify_and_review()"]
```

## 4. Verify & Review Flow

```mermaid
flowchart TD
    A["_verify_and_review(ticket_id)"] --> B{status in\nblocked/todo/\nqueued/failed?}
    B -- Yes --> B1["Skip verification\n(already handled)"]
    B -- No --> C["transition → VERIFYING"]

    C --> D["ensure_pushed():\n1. git add -A + commit\n   (msg: chore: auto-commit remaining changes)\n2. git push\n   (if unpushed)\n3. gh pr create --draft\n   (if no PR)"]

    D --> E["git fetch origin"]
    E --> F["verify_agent_work():\n1. Check commits ahead\n2. Check PR exists"]

    F --> G{passed?}
    G -- No --> H["transition → FAILED\nreason: no commits / no PR\nprocess_queue()"]

    G -- Yes --> I["Update pr_url, pr_number\nclear has_conflicts\nmark_pr_ready()"]
    I --> J{agent enabled\n+ API key?}

    J -- No --> K["transition → AWAITING_MERGE\nprocess_queue()"]
    J -- Yes --> L{review_round\n> MAX_ROUNDS 3?}

    L -- Yes --> M["transition → FAILED\nManual review required\nprocess_queue()"]
    L -- No --> N["transition → REVIEWING"]

    N --> O["agent_review.review_pr():\n1. Get diff (max 50KB)\n2. LLM evaluates:\n   correctness, security,\n   quality, completeness\n3. Return verdict + feedback"]

    O --> P{verdict?}
    P -- approve --> Q["transition → AWAITING_MERGE\nbroadcast\nprocess_queue()"]
    P -- reject --> R["_respawn_with_feedback()"]

    R --> S{active_count\n>= max_sessions?}
    S -- Yes --> T["transition → FAILED\nMax sessions reached"]
    S -- No --> U["transition → IN_PROGRESS\nBuild task: original +\nagent feedback\nstart_session()\n_tail_and_broadcast()"]
```

## 5. Merge Flow

```mermaid
flowchart TD
    A["POST /tickets/{id}/merge"] --> B["Sync PR reviews\nfrom GitHub"]
    B --> C{review_status ==\nchanges_requested?}
    C -- Yes --> C1["HTTP 400\nPR has requested changes"]

    C -- No --> D["get_unresolved_threads()"]
    D --> E{unresolved > 0?}
    E -- Yes --> E1["HTTP 400\nUnresolved conversations"]

    E -- No --> F["get_ci_status()"]
    F --> G{CI status?}

    G -- failed --> G1["HTTP 400\nCI checks failed"]
    G -- pending --> H["transition → MERGING\nstart background:\nwait_for_ci_and_merge()"]

    H --> I["Poll CI every 15s\nmax 10 minutes"]
    I --> J{CI result?}
    J -- passed --> K{re-check\nreview_status?}
    K -- changes_requested --> K1["transition → FAILED\nprocess_queue()"]
    K -- ok --> L
    J -- failed --> J1["Get failed CI log\n(last 80 lines)\ntransition → FAILED\nprocess_queue()"]
    J -- timeout --> J2["transition → FAILED\nCI timeout\nprocess_queue()"]

    G -- passed / no_ci --> L["gh pr merge\n--squash\n--delete-branch"]
    L --> M["transition → MERGED\nset completed_at\ncleanup session + clone\nbroadcast\nprocess_queue()"]
```

## 6. Request Changes & Conflict Resolution

```mermaid
flowchart TD
    A["POST /tickets/{id}/request-changes\n{feedback}"] --> B{active_count\n>= max_sessions?}
    B -- Yes --> B1["HTTP 429"]
    B -- No --> C["transition AWAITING_MERGE → IN_PROGRESS"]

    C --> D["Build task:\noriginal description +\nreview feedback"]

    D --> E{auto_resolve_conversations\nenabled?}
    E -- Yes --> F["get_unresolved_threads()"]
    F --> G{threads found?}
    G -- Yes --> H["Append resolve section:\ngh api graphql mutation\nfor each thread ID"]
    G -- No --> I
    H --> I
    E -- No --> I

    I["Append push verification\ninstruction"] --> J["start_session()\n_tail_and_broadcast()"]

    K["POST /tickets/{id}/resolve-conflicts"] --> L{session already\nactive?}
    L -- Yes --> L1["Return: already_resolving"]
    L -- No --> M["Reset agent_review = []\n(fresh review count)"]
    M --> M1["Broadcast notification:\nAuto-resolving conflicts"]
    M1 --> N["Call request_changes()\nwith conflict feedback:\ngit fetch, rebase,\nresolve, push --force-with-lease"]
```

## 7. Queue System

```mermaid
flowchart TD
    A["POST /tickets/bulk-start\n{ticket_ids}"] --> B["For each ticket"]
    B --> C{status == TODO?}
    C -- No --> B
    C -- Yes --> D{depends_on\nall merged?}
    D -- No --> B
    D -- Yes --> E{active_count\n< max_sessions?}
    E -- Yes --> F["start_ticket()\n→ started list"]
    E -- No --> G["_enqueue_ticket()\ntransition → QUEUED\nZADD tickets:queue\nscore = priority × 1M + seq"]
    F --> B
    G --> B

    H["process_queue()\ncalled when session ends"] --> I{active_count\n< max_sessions?}
    I -- No --> I1["Return: no slot"]
    I -- Yes --> J["ZPOPMIN tickets:queue\n(lowest score = highest priority)"]
    J --> K{ticket found?}
    K -- No --> K1["Return: queue empty"]
    K -- Yes --> L["transition QUEUED → TODO"]
    L --> M["start_ticket()"]
    M -- success --> M1["Return: started"]
    M -- fail --> I
```

## 8. GitHub Webhook Handling

```mermaid
flowchart TD
    A["POST /api/webhooks/github"] --> B{event type?}

    B -- "pull_request\n(closed + merged)" --> C["Find ticket by pr_number\nin AWAITING_MERGE"]
    C --> D{ticket found?}
    D -- Yes --> E["transition → MERGED\nset completed_at\nbroadcast"]
    E --> F["_update_review_branches():\nFor each AWAITING_MERGE/REVIEWING ticket:\ngit merge origin/main\nIf conflict → has_conflicts=true\n→ broadcast notification\n→ auto resolve_conflicts()"]
    F --> G["_sync_kanban_branch_for_project():\nOnly sync affected project"]

    B -- "pull_request_review\n(submitted)" --> H["Find ticket by pr_number"]
    H --> I{review state?}
    I -- APPROVED --> J["Update review_status,\nreviewer"]
    I -- CHANGES_REQUESTED --> K["Update review_status,\nreviewer"]
    I -- COMMENTED --> L["Append as note only\n(no merge gate)"]

    B -- "pull_request_review_comment\n(created)" --> M["Find ticket by pr_number"]
    M --> N["Append note:\nReview comment by user\non path: body"]
```

## 9. Backend Poll Loop (every 10s)

```mermaid
flowchart TD
    A["_pr_poll_loop()\nbackend background task\nevery 10 seconds"] --> B["Step 1: sync_review_status()"]
    B --> C["List all AWAITING_MERGE tickets"]

    C --> D["For each ticket with PR"]
    D --> E["gh pr view --json\nstate, mergedAt, mergeable"]
    E --> F{PR state?}

    F -- MERGED --> G["transition → MERGED\nbroadcast"]
    G --> H["_update_review_branches()\nmerge base into other branches"]

    F -- OPEN --> I{mergeable?}
    I -- CONFLICTING --> J{conflict\nstate changed?}
    J -- Yes --> K["Update has_conflicts\nbroadcast notification\nauto resolve_conflicts()"]
    I -- MERGEABLE --> L["No action"]

    B --> M["Step 2: _check_session_timeouts()"]
    M --> N{timeout_minutes > 0?}
    N -- No --> O["Skip"]
    N -- Yes --> P["For each IN_PROGRESS/BLOCKED\nticket"]
    P --> Q{started_at <\ncutoff?}
    Q -- No --> R["OK, still within limit"]
    Q -- Yes --> S["stop_session()\ntransition → FAILED\nbroadcast notification:\nSession timed out"]
```

## 10. Server Startup Recovery

```mermaid
flowchart TD
    A["Server starts"] --> B["Connect to Redis"]
    B --> C["_migrate_review_to_awaiting_merge()\nRename old 'review' status\nin Redis sets + hashes"]
    C --> D["_recover_orphaned_tickets()"]

    D --> E["Find MERGING tickets"]
    E --> F["transition MERGING → AWAITING_MERGE\n(background task was lost)"]

    D --> G["Find IN_PROGRESS/BLOCKED/\nVERIFYING tickets\nwith dead sessions"]
    G --> H{max_sessions\nreached?}
    H -- Yes --> I["Skip, log warning"]
    H -- No --> J["Re-clone if needed\nstart_session()\n_tail_and_broadcast()"]

    D --> K["Start background loops"]
    K --> L["_pr_poll_loop()\nevery 10s"]
    K --> M["_kanban_sync_loop()\nevery 30s"]
```

## 11. Kanban Claude Code Session (Interactive Terminal)

```mermaid
flowchart TD
    A["Project created /\nTerminal opened"] --> B["kanban_manager.\nensure_session(project_id)"]

    B --> C{tmux session\nalive?}
    C -- Yes --> D["Return existing session"]
    C -- No --> E["Clone repo to\nkanban data dir"]

    E --> F["Generate CLAUDE.md:\n- Project context\n- API tools (curl)\n- Rules & constraints\n- Vision section"]

    F --> G["Write .claude.json\n(trust kanban dir)"]

    G --> H["Create tmux session:\nclaude-hub-kanban-{project_id}"]

    H --> I["Run in loop:\nwhile true; do\n  claude --verbose\n  sleep 2\ndone"]

    I --> J["WebSocket bridge:\n/ws/kanban/{project_id}/terminal"]
    J --> K["xterm.js renders PTY\nuser types → tmux\ntmux output → browser"]

    L["Every 30 seconds"] --> M["sync_kanban_branch():\ngit fetch origin main\ngit merge origin/main"]
    M --> N{conflicts?}
    N -- Yes --> O["git merge --abort\ngit reset --hard origin/main"]
    N -- No --> P["Continue"]

    Q["CLAUDE.md API Tools"] --> R["get_kanban_state:\ncurl /api/projects/{id}/tickets"]
    Q --> S["create_ticket:\ncurl POST /api/tickets"]
    Q --> T["update_ticket:\ncurl PATCH /api/tickets/{id}"]
    Q --> U["reorder_tickets:\ncurl POST /api/tickets/reorder"]
```

## 12. Complete Data Flow Overview

```mermaid
flowchart LR
    subgraph Frontend
        UI[React Kanban Board]
        WS[WebSocket Client]
        Term[xterm.js Terminal]
    end

    subgraph Backend
        API[FastAPI REST]
        WSS[WebSocket Server]
        TM[Ticket Manager\ntickets.py]
        SM[Session Manager\ntmux]
        TA[TicketAgent\nReAct Loop]
        AR[Agent Review\nLLM Eval]
        GV[GitHub Verify\nensure_pushed]
        CI[CI Checker\ngh pr checks]
        CM[Clone Manager\ngit clone]
        CT[Cost Tracker\nbudget limits]
        KM[Kanban Manager\ninteractive terminal]
        PL[Poll Loop\n10s: PR sync + timeout]
    end

    subgraph External
        GH[GitHub API\nPR / Reviews / CI]
        LLM[LLM API\nAnthropic / OpenAI]
        TMUX[tmux sessions]
    end

    subgraph Storage
        Redis[(Redis\ntickets, projects,\nqueue, activity,\ncosts, settings)]
    end

    UI <-->|REST| API
    WS <-->|real-time events| WSS
    Term <-->|PTY bridge| KM

    API --> TM
    TM --> SM
    TM --> CM
    TM --> GV
    TM --> CI
    TM --> AR

    SM --> TMUX
    KM --> TMUX
    TA --> LLM
    AR --> LLM
    CT --> Redis
    PL --> GH
    PL --> SM

    GV --> GH
    CI --> GH
    GH -->|webhooks| API

    TM --> Redis
    SM -.->|tail_log| TA
    TA -.->|tmux_send| TMUX
```
