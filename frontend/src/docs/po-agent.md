# PO Agent

The PO (Product Owner) Agent provides an AI-powered chat interface for project planning and ticket management.

## Accessing PO Chat

1. Open the right panel (panel toggle button in header)
2. Click the **PO Chat** tab
3. Start chatting with the PO Agent

## Capabilities

The PO Agent can help with:

### Ticket Creation
- Describe what you want to build in natural language
- The agent breaks it down into structured tickets
- Tickets are created with proper branch types, descriptions, and dependencies

### Project Planning
- Discuss feature requirements and get implementation suggestions
- Plan sprint work by priority
- Identify potential blockers and dependencies

### Ticket Management
- Ask about ticket status across the board
- Get summaries of in-progress work
- Understand blocking relationships

## How It Works

The PO Agent:
1. Receives your natural language input
2. Has context about your project, tickets, and board state
3. Uses the Anthropic API to reason about your request
4. Can create, update, and manage tickets via API calls
5. Responds with structured feedback and actions taken

## Best Practices

- Be specific about requirements when creating tickets
- Mention dependencies explicitly ("this depends on the auth ticket")
- Use the PO Agent for batch ticket creation when starting a new feature
- Ask follow-up questions to refine ticket descriptions

## Configuration

PO Agent settings are available in **Settings → PO Agent**:
- Model selection
- Custom system prompt
- Context window settings
