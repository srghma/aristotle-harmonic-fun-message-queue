# Aristotle Auto-Queue Runner (Chrome Extension)

A lightweight Google Chrome extension (Manifest V3) that adds an embedded, draggable floating queue manager to **Aristotle** (`aristotle.harmonic.fun`).

It lets you queue up multiple large Markdown prompts, step away, and automatically handles prompt submission, feed scrolling, and budget recovery.

---

## Features

1. **Queue Runner (Controlled via Button)**
   - Start or pause anytime via the **▶ Start Auto-Runner** button.
   - Pops prompts from your local queue one-by-one, writes them cleanly into Aristotle's composer, waits 1 second for React DOM sync, and triggers submission.

2. **Always-On "OUT OF BUDGET" Auto-Recovery (No Duplication)**
   - **Enabled Always:** Works independently of the queue button. Whether you run prompts from the queue or manually type and submit prompts directly in Aristotle, whenever an execution finishes with `OUT OF BUDGET`, the extension automatically detects it.
   - **No Duplicated Prefixes:** Uses regex deduplication to strip any existing `continue previous task:` prefixes before prepending `continue previous task:\n<prev prompt>`. If a prompt runs out of budget multiple times in succession, it will never generate duplicated prefixes (like `continue previous task:\ncontinue previous task:`).
   - If a queued task runs out of budget, recovery takes priority: it continues the task until completion before popping the next item in the queue.

3. **Auto-Scroll Down While Running**
   - While Aristotle is actively thinking/proving, the extension automatically locates the true scrollable feed container and scrolls down to the bottom every **N** seconds (configurable in the UI; default is 5 seconds).

4. **React State Compatibility & Capture Listeners**
   - Dispatches native property setter events for inputs and captures manual keystrokes and button clicks so `lastSentMessage` is always tracked and saved to `chrome.storage.local`.

5. **Queue & Message Persistence**
   - Tasks in queue, scroll settings, and the last sent message survive tab closures and page reloads.
