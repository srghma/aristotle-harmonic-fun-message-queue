# Aristotle Auto-Queue Runner (Chrome Extension)

A lightweight Google Chrome extension (Manifest V3) that adds an embedded, draggable floating queue manager to **Aristotle** (`aristotle.harmonic.fun`).

It lets you queue up multiple large Markdown prompts, steps away, and automatically handles prompt submission, feed scrolling, and budget recovery while you sleep or work on other things.

---

## What It Does

1. **Sequential Task Execution**
   Pops prompts from the queue one-by-one. It safely writes the prompt into Aristotle’s composer, waits 1 second, and triggers the submission (via button click or synthesized `Enter` key).

2. **Full Markdown Support (No Accidental Splitting)**
   Each entry in the text box is treated as a single, unified Markdown message. You can include paragraphs, code blocks, bullet points, and `---` horizontal rules without worrying about your message being cut in pieces.

3. **Smart Idle & Busy Detection**
   Monitors Aristotle's state by observing `[data-testid="composer.stop"]` and the composer textarea. It waits patiently until the current job finishes before typing and sending the next one.

4. **React State Compatibility**
   Uses JavaScript prototype property descriptors to dispatch native `input` and `change` events, ensuring React’s virtual DOM and underlying state stay fully in sync with the injected text.

5. **Auto-Scroll Down While Running**
   While Aristotle is generating output, the extension automatically locates the true scrollable feed container and scrolls down to the bottom every **N** seconds (configurable via the UI; default is 5 seconds).

6. **Automatic "OUT OF BUDGET" Detection & Retry**
   Once Aristotle stops running, the extension scrolls down, inspects the status banner (`border-b border-border` uppercase status label), and verifies the outcome:
   - If the task finished with **`OUT OF BUDGET`** (or anything other than `COMPLETED`), it prepends:
     ```text
     continue previous task:
     <previous message content>
     ```
     straight back to the **front** of the queue, resuming execution immediately on the next iteration without manual intervention.

7. **Queue Persistence & UI Controls**
   - Built with `chrome.storage.local`: your queued tasks and scroll settings survive page reloads and tab closures.
   - Compact collapsible item previews (`expand` / `collapse`) so long Markdown messages don't overwhelm your screen.
   - Draggable header and minimize (`_`) button to keep the UI out of the way.

---

## File Structure

```text
aristotle-auto-queue/
├── manifest.json      # Chrome Manifest V3 configuration
├── content.css        # Modal window styles (dark mode UI)
├── content.js         # Core automation loop and React interaction logic
└── README.md          # Documentation
