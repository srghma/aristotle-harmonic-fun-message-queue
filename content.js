(() => {
  'use strict';

  // =========================================================================
  // 1. Pure Utilities & String Transformers
  // =========================================================================

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const ESCAPE_MAP = Object.freeze({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  });

  const escapeHtml = (str = '') =>
    str.replace(/[&<>"']/g, (m) => ESCAPE_MAP[m] || m);

  /**
   * Checks if a prompt has substantive instruction content.
   * Rejects empty stubs and truncated text ending in ellipses (...).
   */
  const isSubstantivePrompt = (text = '') => {
    if (!text || typeof text !== 'string') return false;
    const trimmed = text.trim();
    if (trimmed.endsWith('...') || trimmed.endsWith('…')) return false;
    const stripped = trimmed
      .replace(/^(continue\s+previous\s+task\s*:\s*)+/i, '')
      .trim();
    return stripped.length > 0;
  };

  /**
   * Deduplicates or prepends "continue previous task:".
   * If already present, leaves it as is; otherwise prepends it.
   */
  const formatContinuationMessage = (prevPrompt = '') => {
    const trimmed = prevPrompt.trim();
    if (!trimmed) {
      return 'continue previous task:';
    }
    if (/^continue\s+previous\s+task\s*:/i.test(trimmed)) {
      return trimmed;
    }
    return `continue previous task:\n${trimmed}`;
  };

  // =========================================================================
  // 2. Functional DOM Query Helpers (Read-Only)
  // =========================================================================

  const query = (selector, root = document) => root.querySelector(selector);
  const queryAll = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const getComposerTextarea = () => query('textarea[data-testid="composer.textarea"]');
  const getStopButton = () => query('button[data-testid="composer.stop"]');

  const getSendButton = () => {
    return (
      query('button[data-testid="composer.solve"]') ||
      query('button[data-testid="composer.send"]') ||
      query('button[data-testid="composer.submit"]') ||
      query('button[data-testid="composer.ask"]') ||
      query('button[aria-label="Solve"], button[aria-label="Send"], button[aria-label="Submit"]') ||
      // Fallback: the primary action button in the composer toolbar (skipping attach-file)
      query('.ml-auto button:not([data-testid*="attach"]):not([aria-label*="Attach"])')
    );
  };

  /**
   * Identifies whether the composer is currently set to 'ask', 'instruct', or 'unknown'
   * based on data-testid and aria-selected="true".
   */
  const getComposerMode = () => {
    const instructTab = query('[data-testid="composer.mode-instruct"]');
    const askTab = query('[data-testid="composer.mode-ask"]');

    if (instructTab && instructTab.getAttribute('aria-selected') === 'true') {
      return 'instruct';
    }
    if (askTab && askTab.getAttribute('aria-selected') === 'true') {
      return 'ask';
    }

    const buttons = queryAll('button');
    const instructBtn = buttons.find(
      (b) => b.innerText?.trim().toUpperCase() === 'INSTRUCT' && b.getAttribute('aria-selected') === 'true'
    );
    if (instructBtn) return 'instruct';

    const askBtn = buttons.find(
      (b) => b.innerText?.trim().toUpperCase() === 'ASK' && b.getAttribute('aria-selected') === 'true'
    );
    if (askBtn) return 'ask';

    return 'unknown';
  };

  const getScrollContainer = () => {
    const explicit = query('[data-scrollable]');
    if (explicit) return explicit;

    const feed = query('[data-feed-group]');
    if (feed) {
      let parent = feed.parentElement;
      while (parent && parent !== document.body) {
        if (parent.scrollHeight > parent.clientHeight && parent.clientHeight > 0) {
          return parent;
        }
        parent = parent.parentElement;
      }
    }
    return document.documentElement || document.body;
  };

  /**
   * Extracts the full text from the message container holding the copy-prompt button.
   */
  const extractPromptTextFromCopyButton = (copyBtn) => {
    const wrapper = copyBtn.closest('div.relative') || copyBtn.parentElement?.parentElement;
    if (!wrapper) return '';

    const textEl = wrapper.querySelector('.text-body-md, .whitespace-pre-wrap, [class*="whitespace-pre-wrap"]');
    if (textEl && textEl.textContent.trim()) {
      return textEl.textContent.trim();
    }

    const clone = wrapper.cloneNode(true);
    clone.querySelectorAll('button, svg, [data-slot="button"]').forEach((el) => el.remove());
    return clone.textContent.trim();
  };

  /**
   * Scans visible DOM for actual chat messages (NOT header titles or task rename buttons).
   */
  const scanSubstantiveUserMessageInDOM = () => {
    // 1. Direct copy-prompt buttons (located exclusively on user chat messages)
    const copyBtns = queryAll('button[data-testid="log.copy-prompt"], button[aria-label="Copy prompt"], button[title="Copy prompt"]');
    for (let i = copyBtns.length - 1; i >= 0; i--) {
      const text = extractPromptTextFromCopyButton(copyBtns[i]);
      if (isSubstantivePrompt(text)) {
        return text;
      }
    }

    // 2. Feed items containing avatar and whitespace-pre-wrap text
    const feedItems = queryAll('[data-feed-item]');
    for (let i = feedItems.length - 1; i >= 0; i--) {
      const item = feedItems[i];
      const hasAvatar = Boolean(query('[data-slot="avatar"], [data-slot="avatar-image"], img.rounded-full', item));
      if (hasAvatar) {
        const textDiv = query('.whitespace-pre-wrap, .text-body-md', item);
        if (textDiv) {
          const text = (textDiv.innerText || textDiv.textContent || '').trim();
          if (isSubstantivePrompt(text)) {
            return text;
          }
        }
      }
    }

    return '';
  };

  /**
   * Scans for the last user prompt message.
   * If virtualized out of the DOM, clicks Aristotle's built-in "Scroll to top of task"
   * jump button (log.task-jump-edge) to load the message, extracts it, and restores scroll position.
   */
  const findLastUserPromptInDOM = async (allowScroll = true) => {
    // Step 1: Check if already rendered in DOM
    let prompt = scanSubstantiveUserMessageInDOM();
    if (prompt) return prompt;

    if (!allowScroll) return '';

    const container = getScrollContainer();
    const originalScrollTop = container ? container.scrollTop : window.scrollY;

    // Step 2: Click Aristotle's built-in "Scroll to top of task" button
    const jumpButtons = queryAll('button[data-testid="log.task-jump-edge"], button[aria-label*="Scroll to top of task"], button[title*="Scroll to top of task"]');
    if (jumpButtons.length > 0) {
      const lastJumpBtn = jumpButtons[jumpButtons.length - 1];
      lastJumpBtn.click();
      await sleep(350);

      prompt = scanSubstantiveUserMessageInDOM();
      if (prompt) {
        if (container) container.scrollTop = originalScrollTop;
        else window.scrollTo(0, originalScrollTop);
        return prompt;
      }
    }

    // Step 3: Gentle scroll-up fallback if jump button did not mount the item
    if (container && container.scrollTop > 0) {
      let attempts = 0;
      while (!prompt && container.scrollTop > 0 && attempts < 8) {
        attempts++;
        container.scrollTop = Math.max(0, container.scrollTop - container.clientHeight * 0.7);
        await sleep(250);
        prompt = scanSubstantiveUserMessageInDOM();
      }
    }

    // Restore scroll position
    if (container) container.scrollTop = originalScrollTop;
    else window.scrollTo(0, originalScrollTop);

    return prompt;
  };

  /**
    * Targets specifically the status of the LAST task group in Aristotle:
    * 1. Badge inside the last [data-feed-header]
    * 2. "ran out of time" terminal banner in the feed
    */
  const getLastExecutionInfo = () => {
    // Strategy 1: Check the badge of the LAST task group header
    const feedHeaders = queryAll('[data-feed-header]');
    if (feedHeaders.length > 0) {
      const lastHeader = feedHeaders[feedHeaders.length - 1];
      const badge = query('[data-slot="tooltip-trigger"], .group\\/badge, span.uppercase', lastHeader);
      if (badge && badge.textContent.trim()) {
        return {
          element: lastHeader, // Use the header element to attach data-aq-handled
          status: badge.textContent.trim().toUpperCase(),
        };
      }
    }

    // Strategy 2: Check for terminal "Aristotle ran out of time" in the feed
    const terminalSpans = queryAll('span.text-body-md, div.text-body-md, [data-feed-item] span');
    for (let i = terminalSpans.length - 1; i >= 0; i--) {
      const el = terminalSpans[i];
      if (/ran out of time/i.test(el.textContent || '')) {
        return {
          element: el,
          status: 'OUT OF BUDGET',
        };
      }
    }

    // Strategy 3: Specific status badges (ignoring code blocks/numbers)
    const badges = queryAll('[data-slot="tooltip-trigger"][data-variant="purple"], span.bg-purple\\/15');
    if (badges.length > 0) {
      const lastBadge = badges[badges.length - 1];
      return {
        element: lastBadge,
        status: lastBadge.textContent.trim().toUpperCase(),
      };
    }

    return { element: null, status: 'UNKNOWN' };
  };

  const isOutOfBudgetStatus = (status = '') =>
    status.includes('OUT OF BUDGET') ||
    status.includes('RAN OUT OF TIME') ||
    (!status.includes('COMPLETED') && status.includes('BUDGET'));

  // =========================================================================
  // 3. Immutable State Store
  // =========================================================================

  const createStore = (initialState, subscriber = () => { }) => {
    let state = Object.freeze({ ...initialState });
    return {
      getState: () => state,
      setState: (updater) => {
        const nextState = Object.freeze(
          typeof updater === 'function' ? updater(state) : { ...state, ...updater }
        );
        if (nextState !== state) {
          state = nextState;
          subscriber(state);
        }
        return state;
      },
    };
  };

  const INITIAL_STATE = Object.freeze({
    queue: [],
    isRunnerActive: false,
    autoBudgetRecoveryEnabled: true,
    autoScrollEnabled: false,
    scrollIntervalSeconds: 5,
    lastSentMessage: '',
    composerDraft: '',
    isBusy: false,
    isRecoveringBudget: false,
    lastScrollTimestamp: 0,
    handledFallbackKey: '',
  });

  const persistState = ({ queue, scrollIntervalSeconds, autoScrollEnabled, autoBudgetRecoveryEnabled, lastSentMessage }) => {
    chrome?.storage?.local?.set({
      aristotle_queue: queue,
      aristotle_scroll_interval: scrollIntervalSeconds,
      aristotle_autoscroll_enabled: autoScrollEnabled,
      aristotle_auto_budget_recovery: autoBudgetRecoveryEnabled,
      aristotle_last_sent_message: lastSentMessage,
    });
  };

  const store = createStore(INITIAL_STATE, persistState);

  // =========================================================================
  // 4. Side-Effecting DOM Drivers
  // =========================================================================

  const setNativeValue = (element, value) => {
    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
    const protoSetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')?.set;

    if (protoSetter && valueSetter !== protoSetter) {
      protoSetter.call(element, value);
    } else if (valueSetter) {
      valueSetter.call(element, value);
    } else {
      element.value = value;
    }

    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const triggerSubmit = (textarea) => {
    const sendBtn = getSendButton();
    if (sendBtn && !sendBtn.disabled) {
      sendBtn.click();
      return;
    }

    // Fallback if button isn't found
    textarea.focus();
    const eventInit = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
    textarea.dispatchEvent(new KeyboardEvent('keydown', eventInit));
    textarea.dispatchEvent(new KeyboardEvent('keypress', eventInit));
    textarea.dispatchEvent(new KeyboardEvent('keyup', eventInit));
  };

  const scrollFeedToBottom = () => {
    const container = getScrollContainer();
    if (container) container.scrollTop = container.scrollHeight;
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  };

  const submitPrompt = async (textarea, message) => {
    textarea.focus();
    setNativeValue(textarea, message);
    await sleep(1000);
    triggerSubmit(textarea);
  };

  // =========================================================================
  // 5. User Input Monitoring
  // =========================================================================

  const resolveLastPrompt = (state) =>
    state.lastSentMessage.trim() || state.composerDraft.trim();

  const registerInputCaptureListeners = (onNewPromptCaptured) => {
    document.addEventListener(
      'input',
      (e) => {
        const textarea = getComposerTextarea();
        if (e.target === textarea && textarea.value.trim()) {
          store.setState((prev) => ({ ...prev, composerDraft: textarea.value.trim() }));
        }
      },
      true
    );

    const onCommit = () => {
      const textarea = getComposerTextarea();
      const text = (textarea?.value || '').trim() || store.getState().composerDraft;
      if (text && isSubstantivePrompt(text)) {
        store.setState((prev) => ({ ...prev, lastSentMessage: text, composerDraft: '' }));
        if (onNewPromptCaptured) onNewPromptCaptured(text);
      }
    };

    document.addEventListener(
      'keydown',
      (e) => {
        if (e.target === getComposerTextarea() && e.key === 'Enter' && !e.shiftKey) onCommit();
      },
      true
    );

    document.addEventListener(
      'click',
      (e) => {
        const sendBtn = getSendButton();
        if (sendBtn && (sendBtn === e.target || sendBtn.contains(e.target))) onCommit();
      },
      true
    );
  };

  // =========================================================================
  // 6. Modal Construction & View Rendering
  // =========================================================================

  const createModalElement = () => {
    const modal = document.createElement('div');
    modal.id = 'aristotle-queue-modal';
    modal.innerHTML = `
      <div id="aristotle-queue-header">
        <h3><span id="aristotle-status-dot" class="idle"></span> Aristotle Auto-Queue</h3>
        <span id="aq-toggle-min" style="cursor:pointer;color:#71717a;">_</span>
      </div>
      <div id="aristotle-queue-body">

        <!-- Big Button: Start / Pause autosubmit 'continue' on 'out of budget' -->
        <button id="aq-btn-toggle-budget" class="aq-btn aq-btn-big aq-btn-primary">
          ▶ Start autosubmit "continue" on "out of budget"
        </button>

        <!-- Runner Controls Row: Start button on left, Auto-scroll on right -->
        <div class="aq-runner-row">
          <button id="aq-btn-start" class="aq-btn aq-btn-secondary">▶ Start Auto-Runner</button>
          <div class="aq-autoscroll-control">
            <label class="aq-checkbox-label">
              <input type="checkbox" id="aq-toggle-autoscroll" />
              <span>Auto-scroll</span>
            </label>
            <div class="aq-interval-box">
              <input type="number" id="aq-scroll-interval" class="aq-number-input" value="5" min="1" max="60" /> s
            </div>
          </div>
        </div>

        <!-- Confirmed Last User Task Card -->
        <div class="aq-card">
          <div class="aq-card-header">
            <span>Last User Task (Confirmed)</span>
            <button id="aq-btn-rescan" class="aq-link-btn" title="Scan feed for last user prompt">🔄 Scan Feed</button>
          </div>
          <textarea id="aq-confirmed-prompt" class="aq-mono-area" rows="3" placeholder="Scanning feed or waiting for input..."></textarea>
          <div class="aq-card-hint">Used for auto-submitting continuation when out of budget.</div>
        </div>

        <!-- Queue Input & Actions -->
        <textarea id="aristotle-input-area" placeholder="Paste full Markdown message here..."></textarea>
        <div class="aq-btn-row">
          <button id="aq-btn-add" class="aq-btn aq-btn-secondary">+ Add Message to Queue</button>
          <button id="aq-btn-clear" class="aq-btn aq-btn-danger">Clear</button>
        </div>

        <!-- Queue List -->
        <div style="font-weight:600; font-size:11px; text-transform:uppercase; color:#71717a;">
          Queue (<span id="aq-count">0</span>)
        </div>
        <div id="aq-queue-list-container">
          <div id="aq-queue-list"></div>
        </div>

        <div id="aq-log">Status: Idle</div>
      </div>
    `;
    document.body.appendChild(modal);
    return modal;
  };

  const bindUI = (modal) => {
    const inputArea = query('#aristotle-input-area', modal);
    const confirmedPromptInput = query('#aq-confirmed-prompt', modal);
    const rescanBtn = query('#aq-btn-rescan', modal);
    const budgetToggleBtn = query('#aq-btn-toggle-budget', modal);
    const addBtn = query('#aq-btn-add', modal);
    const clearBtn = query('#aq-btn-clear', modal);
    const startBtn = query('#aq-btn-start', modal);
    const queueList = query('#aq-queue-list', modal);
    const queueCount = query('#aq-count', modal);
    const statusDot = query('#aristotle-status-dot', modal);
    const logBox = query('#aq-log', modal);
    const body = query('#aristotle-queue-body', modal);
    const toggleMin = query('#aq-toggle-min', modal);
    const autoScrollCheckbox = query('#aq-toggle-autoscroll', modal);
    const scrollIntervalInput = query('#aq-scroll-interval', modal);

    const setLog = (text, statusType = 'idle') => {
      logBox.textContent = `Status: ${text}`;
      statusDot.className = statusType;
    };

    const updateBudgetButtonUI = (enabled) => {
      if (enabled) {
        budgetToggleBtn.textContent = '⏸ Pause autosubmit "continue" on "out of budget"';
        budgetToggleBtn.classList.remove('aq-btn-primary');
        budgetToggleBtn.classList.add('aq-btn-danger');
      } else {
        budgetToggleBtn.textContent = '▶ Start autosubmit "continue" on "out of budget"';
        budgetToggleBtn.classList.remove('aq-btn-danger');
        budgetToggleBtn.classList.add('aq-btn-primary');
      }
    };

    const renderQueue = (queue) => {
      queueCount.textContent = queue.length;
      if (queue.length === 0) {
        queueList.innerHTML = `<div style="padding: 10px; color: #52525b; text-align: center;">Queue is empty</div>`;
        return;
      }

      queueList.innerHTML = queue
        .map(
          (text, idx) => `
            <div class="aq-item" data-idx="${idx}">
              <div class="aq-item-header">
                <span style="color:#71717a; font-family:monospace;">#${idx + 1} (${text.length} chars)</span>
                <div style="display:flex; gap:8px;">
                  <span class="aq-item-toggle" data-idx="${idx}">expand</span>
                  <span class="aq-item-remove" data-idx="${idx}">&times;</span>
                </div>
              </div>
              <div class="aq-item-text collapsed" id="aq-text-${idx}">${escapeHtml(text)}</div>
            </div>
          `
        )
        .join('');

      queryAll('.aq-item-remove', queueList).forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const index = parseInt(e.target.dataset.idx, 10);
          store.setState((prev) => ({
            ...prev,
            queue: prev.queue.filter((_, i) => i !== index),
          }));
          renderQueue(store.getState().queue);
        });
      });

      queryAll('.aq-item-toggle', queueList).forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const textEl = query(`#aq-text-${e.target.dataset.idx}`, queueList);
          const isCollapsed = textEl.classList.toggle('collapsed');
          e.target.textContent = isCollapsed ? 'expand' : 'collapse';
        });
      });
    };

    confirmedPromptInput.addEventListener('input', () => {
      const val = confirmedPromptInput.value.trim();
      store.setState((prev) => ({ ...prev, lastSentMessage: val }));
    });

    const scanAndConfirmPrompt = async () => {
      setLog('Scanning feed for last user prompt...', 'waiting');
      const detected = await findLastUserPromptInDOM(true);
      if (detected && isSubstantivePrompt(detected)) {
        confirmedPromptInput.value = detected;
        store.setState((prev) => ({ ...prev, lastSentMessage: detected }));
        setLog('Found last user task. Please confirm above.', 'idle');
      } else {
        setLog('No substantive user task found yet. Type it above or scan again.', 'idle');
      }
    };

    rescanBtn.addEventListener('click', scanAndConfirmPrompt);

    budgetToggleBtn.addEventListener('click', () => {
      const nextState = !store.getState().autoBudgetRecoveryEnabled;
      store.setState((prev) => ({ ...prev, autoBudgetRecoveryEnabled: nextState }));
      updateBudgetButtonUI(nextState);
      if (nextState) {
        scanAndConfirmPrompt();
        setLog('Autosubmit on Out of Budget: ENABLED', 'active');
      } else {
        setLog('Autosubmit on Out of Budget: PAUSED', 'idle');
      }
    });

    addBtn.addEventListener('click', () => {
      const raw = inputArea.value.trim();
      if (!raw) return;
      store.setState((prev) => ({ ...prev, queue: [...prev.queue, raw] }));
      inputArea.value = '';
      renderQueue(store.getState().queue);
    });

    clearBtn.addEventListener('click', () => {
      const { isRunnerActive } = store.getState();
      if (isRunnerActive && !confirm('Pause runner and clear queue?')) return;
      if (isRunnerActive) toggleRunner();
      store.setState((prev) => ({ ...prev, queue: [] }));
      renderQueue([]);
    });

    const toggleRunner = () => {
      const nextActive = !store.getState().isRunnerActive;
      if (nextActive && store.getState().queue.length === 0) {
        alert('Queue is empty! Add a message first.');
        return;
      }

      store.setState((prev) => ({ ...prev, isRunnerActive: nextActive }));

      startBtn.textContent = nextActive ? '⏸ Pause Auto-Runner' : '▶ Start Auto-Runner';
      startBtn.classList.toggle('aq-btn-secondary', !nextActive);
      startBtn.classList.toggle('aq-btn-danger', nextActive);
      setLog(nextActive ? 'Auto-Runner started' : 'Auto-Runner paused', nextActive ? 'active' : 'idle');
    };

    startBtn.addEventListener('click', toggleRunner);

    autoScrollCheckbox.addEventListener('change', () => {
      store.setState((prev) => ({ ...prev, autoScrollEnabled: autoScrollCheckbox.checked }));
    });

    scrollIntervalInput.addEventListener('change', () => {
      const val = parseInt(scrollIntervalInput.value, 10);
      const safeVal = !isNaN(val) && val > 0 ? val : 5;
      store.setState((prev) => ({ ...prev, scrollIntervalSeconds: safeVal }));
    });

    toggleMin.addEventListener('click', () => {
      const isHidden = body.style.display === 'none';
      body.style.display = isHidden ? 'flex' : 'none';
      toggleMin.textContent = isHidden ? '_' : '□';
    });

    let dragOffset = null;
    const header = query('#aristotle-queue-header', modal);
    header.addEventListener('mousedown', (e) => {
      if (e.target === toggleMin) return;
      dragOffset = { x: e.clientX - modal.offsetLeft, y: e.clientY - modal.offsetTop };
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragOffset) return;
      modal.style.left = `${Math.max(10, e.clientX - dragOffset.x)}px`;
      modal.style.top = `${Math.max(10, e.clientY - dragOffset.y)}px`;
      modal.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => {
      dragOffset = null;
    });

    return {
      setLog,
      renderQueue,
      updateBudgetButtonUI,
      scanAndConfirmPrompt,
      confirmedPromptInput,
      scrollIntervalInput,
      autoScrollCheckbox,
      toggleRunner,
    };
  };

  // =========================================================================
  // 7. Continuous Automation Loop
  // =========================================================================

  const monitorLoop = async (ui) => {
    while (true) {
      try {
        const state = store.getState();
        const textarea = getComposerTextarea();
        const currentlyBusy = Boolean(getStopButton());

        // 1. Aristotle working state -> auto-scroll if enabled
        if (currentlyBusy) {
          const now = Date.now();
          if (state.autoScrollEnabled && now - state.lastScrollTimestamp >= state.scrollIntervalSeconds * 1000) {
            scrollFeedToBottom();
            store.setState((prev) => ({ ...prev, lastScrollTimestamp: now }));
          }

          if (!state.isBusy) {
            store.setState((prev) => ({ ...prev, isBusy: true, handledFallbackKey: '' }));
            ui.setLog(
              state.autoScrollEnabled
                ? 'Aristotle working... auto-scrolling'
                : 'Aristotle working...',
              'waiting'
            );
          }

          await sleep(1000);
          continue;
        }

        // 2. Aristotle task stopped transition
        if (state.isBusy && !currentlyBusy) {
          store.setState((prev) => ({ ...prev, isBusy: false }));
          ui.setLog('Task stopped. Checking outcome...', 'waiting');
          if (state.autoScrollEnabled) {
            scrollFeedToBottom();
            await sleep(1500);
            scrollFeedToBottom();
          } else {
            await sleep(1500);
          }
        }

        // 3. OUT OF BUDGET Detection & Recovery (Only if enabled via big button)
        const execInfo = getLastExecutionInfo();
        const isBudgetExhausted = isOutOfBudgetStatus(execInfo.status);
        const fallbackKey = `${execInfo.status}_${state.lastSentMessage}`;
        const isAlreadyHandled = execInfo.element
          ? execInfo.element.dataset.aqHandled === 'true'
          : state.handledFallbackKey === fallbackKey;

        if (state.autoBudgetRecoveryEnabled && isBudgetExhausted && !isAlreadyHandled && !state.isRecoveringBudget && textarea && !textarea.disabled) {
          const mode = getComposerMode();

          // Error guard: UNKNOWN composer mode
          if (mode === 'unknown') {
            ui.setLog('ERROR: Composer mode is UNKNOWN (neither Instruct nor Ask). Continuation aborted.', 'idle');
            await sleep(2000);
            continue;
          }

          // Guard: ASK mode (must NOT send continuation)
          if (mode === 'ask') {
            if (execInfo.element) {
              execInfo.element.dataset.aqHandled = 'true';
            } else {
              store.setState((prev) => ({ ...prev, handledFallbackKey: fallbackKey }));
            }
            ui.setLog('OUT OF BUDGET detected, but composer is in ASK mode. Continuation skipped.', 'idle');
            await sleep(1500);
            continue;
          }

          // Mode is 'instruct': Proceed with continuation
          if (execInfo.element) {
            execInfo.element.dataset.aqHandled = 'true';
          } else {
            store.setState((prev) => ({ ...prev, handledFallbackKey: fallbackKey }));
          }

          store.setState((prev) => ({ ...prev, isRecoveringBudget: true }));
          ui.setLog('OUT OF BUDGET detected in Instruct mode! Preparing continuation...', 'waiting');
          await sleep(1200);

          const basePrompt = resolveLastPrompt(state);
          const continuationPrompt = formatContinuationMessage(basePrompt);

          ui.setLog('Writing continuation task...', 'active');
          await submitPrompt(textarea, continuationPrompt);

          store.setState((prev) => ({
            ...prev,
            lastSentMessage: continuationPrompt,
            composerDraft: '',
            isRecoveringBudget: false,
          }));

          ui.confirmedPromptInput.value = continuationPrompt;

          let attempts = 0;
          while (attempts++ < 20) {
            await sleep(500);
            if (getStopButton()) {
              store.setState((prev) => ({ ...prev, isBusy: true }));
              break;
            }
          }

          ui.setLog('Continuation task active. Running...', 'waiting');
          continue;
        }

        if (isBudgetExhausted && !isAlreadyHandled) {
          await sleep(1000);
          continue;
        }

        // 4. QUEUE RUNNER: Process queued tasks (Only when enabled via button)
        if (state.isRunnerActive) {
          if (state.queue.length > 0) {
            const isReady = textarea && !textarea.disabled && !getStopButton();
            if (isReady) {
              const [nextTask, ...remainingQueue] = state.queue;

              ui.setLog(`Typing task (${state.queue.length} in queue)...`, 'active');
              await submitPrompt(textarea, nextTask);

              store.setState((prev) => ({
                ...prev,
                queue: remainingQueue,
                lastSentMessage: nextTask,
                composerDraft: '',
              }));

              ui.confirmedPromptInput.value = nextTask;
              ui.renderQueue(remainingQueue);

              let attempts = 0;
              while (attempts++ < 20) {
                await sleep(500);
                if (getStopButton()) {
                  store.setState((prev) => ({ ...prev, isBusy: true }));
                  break;
                }
              }
              continue;
            }
          } else {
            ui.setLog('All tasks in queue completed!', 'active');
            ui.toggleRunner();
          }
        }
      } catch (err) {
        console.error('[Aristotle Auto-Queue] Monitor loop error:', err);
      }

      await sleep(1000);
    }
  };

  // =========================================================================
  // 8. Initialization (IIFE Bootstrapper)
  // =========================================================================

  const init = () => {
    const modal = createModalElement();
    const ui = bindUI(modal);

    registerInputCaptureListeners((newPrompt) => {
      ui.confirmedPromptInput.value = newPrompt;
    });

    chrome?.storage?.local?.get(
      [
        'aristotle_queue',
        'aristotle_scroll_interval',
        'aristotle_autoscroll_enabled',
        'aristotle_auto_budget_recovery',
        'aristotle_last_sent_message',
      ],
      async (res) => {
        const autoScroll = typeof res?.aristotle_autoscroll_enabled === 'boolean'
          ? res.aristotle_autoscroll_enabled
          : false;

        const autoBudget = typeof res?.aristotle_auto_budget_recovery === 'boolean'
          ? res.aristotle_auto_budget_recovery
          : true;

        const storedLastPrompt = res?.aristotle_last_sent_message || '';
        const hasSubstantiveStored = isSubstantivePrompt(storedLastPrompt);

        store.setState((prev) => ({
          ...prev,
          queue: Array.isArray(res?.aristotle_queue) ? res.aristotle_queue : prev.queue,
          scrollIntervalSeconds: res?.aristotle_scroll_interval || prev.scrollIntervalSeconds,
          autoScrollEnabled: autoScroll,
          autoBudgetRecoveryEnabled: autoBudget,
          lastSentMessage: hasSubstantiveStored ? storedLastPrompt : '',
        }));

        ui.autoScrollCheckbox.checked = autoScroll;
        ui.scrollIntervalInput.value = store.getState().scrollIntervalSeconds;
        ui.updateBudgetButtonUI(autoBudget);
        ui.renderQueue(store.getState().queue);

        if (hasSubstantiveStored) {
          ui.confirmedPromptInput.value = storedLastPrompt;
        }

        // On entry: scan feed for the last substantive task
        if (autoBudget) {
          await sleep(600);
          await ui.scanAndConfirmPrompt();

          if (!isSubstantivePrompt(store.getState().lastSentMessage)) {
            await sleep(1500);
            await ui.scanAndConfirmPrompt();
          }
        }

        monitorLoop(ui);
      }
    );
  };

  init();
})();
