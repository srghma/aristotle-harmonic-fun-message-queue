(() => {
  'use strict';

  // =========================================================================
  // 1. Functional Primitives & Combinators
  // =========================================================================

  const pipe = (...fns) => (x) => fns.reduce((v, f) => f(v), x);

  const curry = (fn) => {
    const arity = fn.length;
    return function curried(...args) {
      return args.length >= arity
        ? fn(...args)
        : (...more) => curried(...args, ...more);
    };
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const trim = (str = '') => (typeof str === 'string' ? str.trim() : '');
  const toUpper = (str = '') => (typeof str === 'string' ? str.toUpperCase() : '');

  // const prop = curry((key, obj) => obj?.[key]);
  // const hasProp = curry((key, obj) => Boolean(obj && Object.prototype.hasOwnProperty.call(obj, key)));

  // Array pure transforms
  const append = curry((item, arr) => [...arr, item]);
  const removeAt = curry((index, arr) => arr.filter((_, i) => i !== index));
  const updateAt = curry((index, val, arr) => arr.map((item, i) => (i === index ? val : item)));

  // String formatting
  const ESCAPE_MAP = Object.freeze({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  });

  const escapeHtml = (str = '') =>
    str.replace(/[&<>"']/g, (m) => ESCAPE_MAP[m] || m);

  // =========================================================================
  // 2. Pure Domain Logic & Predicates
  // =========================================================================

  const calculateStats = (text = '') => ({
    chars: text.length,
    lines: text ? text.split(/\r\n|\r|\n/).length : 0,
  });

  const stripContinuationPrefixes = (text = '') =>
    text.replace(/^(continue\s+previous\s+task\s*:\s*)+/i, '');

  const isSubstantivePrompt = (text = '') => {
    if (!text || typeof text !== 'string') return false;
    const trimmed = trim(text);
    if (trimmed.endsWith('...') || trimmed.endsWith('…')) return false;
    return pipe(stripContinuationPrefixes, trim, (s) => s.length > 0)(trimmed);
  };

  const formatContinuationMessage = (prevPrompt = '') => {
    const trimmed = trim(prevPrompt);
    if (!trimmed) return 'continue previous task:';
    if (/^continue\s+previous\s+task\s*:/i.test(trimmed)) return trimmed;
    return `continue previous task:\n${trimmed}`;
  };

  const isOutOfBudgetStatus = (status = '') => {
    const s = toUpper(status);
    return (
      s.includes('OUT OF BUDGET') ||
      s.includes('RAN OUT OF TIME') ||
      (!s.includes('COMPLETED') && s.includes('BUDGET'))
    );
  };

  // =========================================================================
  // 3. Declarative DOM Selectors (Pure Read queries)
  // =========================================================================

  const query = curry((selector, root) => root.querySelector(selector));
  const queryAll = curry((selector, root) => Array.from(root.querySelectorAll(selector)));

  const selectComposerTextarea = () => query('textarea[data-testid="composer.textarea"]', document);

  const selectStopButton = () =>
    query('button[data-testid="composer.stop"]', document) ||
    query('button[aria-label*="Stop"]', document) ||
    query('button[data-testid="workspace.section-stop"]', document);

  const selectSendButton = () =>
    query('button[data-testid="composer.solve"]', document) ||
    query('button[data-testid="composer.send"]', document) ||
    query('button[data-testid="composer.submit"]', document) ||
    query('button[data-testid="composer.ask"]', document) ||
    query('button[aria-label="Solve"], button[aria-label="Send"], button[aria-label="Submit"]', document) ||
    query('.ml-auto button:not([data-testid*="attach"]):not([aria-label*="Attach"])', document);

  const selectComposerMode = () => {
    const askTab = query('[data-testid="composer.mode-ask"]', document);
    if (askTab && (askTab.getAttribute('aria-selected') === 'true' || askTab.classList.contains('active'))) {
      return 'ask';
    }

    const askBtn = queryAll('button', document).find(
      (b) => toUpper(b.innerText).trim() === 'ASK' && b.getAttribute('aria-selected') === 'true'
    );
    if (askBtn) return 'ask';

    const instructTab = query('[data-testid="composer.mode-instruct"]', document);
    if (instructTab && (instructTab.getAttribute('aria-selected') === 'true' || instructTab.classList.contains('active'))) {
      return 'instruct';
    }

    const solveBtn = query('button[data-testid="composer.solve"], button[aria-label="Solve"]', document);
    const agentControls = query('[role="toolbar"][aria-label="Agent controls"]', document);
    const textarea = selectComposerTextarea();
    const hasTellAristotle = Boolean(textarea && /tell aristotle/i.test(textarea.getAttribute('aria-label') || ''));

    if (solveBtn || agentControls || hasTellAristotle) return 'agent';
    return textarea ? 'default' : 'unknown';
  };

  const selectScrollContainer = () => {
    const explicit = query('[data-scrollable]', document);
    if (explicit) return explicit;

    const findScrollableParent = (el) => {
      let current = el?.parentElement;
      while (current && current !== document.body) {
        if (current.scrollHeight > current.clientHeight && current.clientHeight > 0) return current;
        current = current.parentElement;
      }
      return null;
    };

    const logParent = findScrollableParent(query('[role="log"]', document));
    if (logParent) return logParent;

    const feedParent = findScrollableParent(query('[data-feed-group]', document));
    if (feedParent) return feedParent;

    return document.documentElement || document.body;
  };

  const selectExecutionStatus = () => {
    // Pipeline of detection strategies: first truthy match wins
    const strategies = [
      () => {
        const toolbar = query('[role="toolbar"][aria-label="Agent controls"]', document);
        const badge = toolbar ? query('.text-text-purple, [class*="text-purple"]', toolbar) : null;
        return badge && trim(badge.textContent)
          ? { element: badge, status: toUpper(badge.textContent).trim() }
          : null;
      },
      () => {
        const badges = queryAll('.text-text-purple, [class*="text-purple"], [data-variant="purple"], span.bg-purple\\/15', document);
        const match = badges.reverse().find((b) => /budget|time/i.test(b.textContent || ''));
        return match ? { element: match, status: toUpper(match.textContent).trim() } : null;
      },
      () => {
        const headers = queryAll('[data-feed-header]', document);
        const lastHeader = headers[headers.length - 1];
        if (!lastHeader) return null;
        const badge = query('[data-slot="tooltip-trigger"], .group\\/badge, span.uppercase, .text-text-purple', lastHeader);
        return badge && trim(badge.textContent)
          ? { element: lastHeader, status: toUpper(badge.textContent).trim() }
          : null;
      },
      () => {
        const spans = queryAll('span.text-body-md, div.text-body-md, [data-feed-item] span, [role="log"] span', document);
        const match = spans.reverse().find((el) => /ran out of time|out of budget/i.test(el.textContent || ''));
        return match ? { element: match, status: toUpper(match.textContent).trim() } : null;
      },
    ];

    for (const strat of strategies) {
      const match = strat();
      if (match) return match;
    }
    return { element: null, status: 'UNKNOWN' };
  };

  const extractPromptTextFromButton = (copyBtn) => {
    const wrapper = copyBtn.closest('div.relative') || copyBtn.parentElement?.parentElement;
    if (!wrapper) return '';
    const textEl = query('.text-body-md, .whitespace-pre-wrap, [class*="whitespace-pre-wrap"]', wrapper);
    if (textEl && trim(textEl.textContent)) return trim(textEl.textContent);

    const clone = wrapper.cloneNode(true);
    queryAll('button, svg, [data-slot="button"]', clone).forEach((el) => el.remove());
    return trim(clone.textContent);
  };

  const scanFeedForUserPrompt = () => {
    const copyBtns = queryAll('button[data-testid="log.copy-prompt"], button[aria-label="Copy prompt"]', document);
    const fromCopy = copyBtns
      .slice()
      .reverse()
      .map(extractPromptTextFromButton)
      .find(isSubstantivePrompt);
    if (fromCopy) return fromCopy;

    const feedItems = queryAll('[data-feed-item]', document);
    return feedItems
      .slice()
      .reverse()
      .filter((item) => Boolean(query('[data-slot="avatar"], [data-slot="avatar-image"], img.rounded-full', item)))
      .map((item) => trim(query('.whitespace-pre-wrap, .text-body-md', item)?.innerText || query('.whitespace-pre-wrap, .text-body-md', item)?.textContent))
      .find(isSubstantivePrompt) || '';
  };

  const findLastPromptWithFallbackScroll = async () => {
    const prompt = scanFeedForUserPrompt();
    if (prompt) return prompt;

    const container = selectScrollContainer();
    const originalScrollTop = container ? container.scrollTop : window.scrollY;

    const jumpButtons = queryAll('button[data-testid="log.task-jump-edge"], button[aria-label*="Scroll to top of task"]', document);
    if (jumpButtons.length > 0) {
      jumpButtons[jumpButtons.length - 1].click();
      await sleep(350);
      const scrolledPrompt = scanFeedForUserPrompt();
      if (scrolledPrompt) {
        if (container) container.scrollTop = originalScrollTop;
        else window.scrollTo(0, originalScrollTop);
        return scrolledPrompt;
      }
    }

    if (container && container.scrollTop > 0) {
      let attempts = 0;
      while (attempts++ < 6 && container.scrollTop > 0) {
        container.scrollTop = Math.max(0, container.scrollTop - container.clientHeight * 0.7);
        await sleep(200);
        const retryPrompt = scanFeedForUserPrompt();
        if (retryPrompt) {
          container.scrollTop = originalScrollTop;
          return retryPrompt;
        }
      }
    }

    if (container) container.scrollTop = originalScrollTop;
    else window.scrollTo(0, originalScrollTop);
    return '';
  };

  // =========================================================================
  // 4. State Architecture (Redux / Elm Pure Reducer Pattern)
  // =========================================================================

  const STORAGE_KEYS = Object.freeze({
    QUEUE: 'aristotle_queue',
    RUNNER_ACTIVE: 'aristotle_runner_active',
    BUDGET_RECOVERY: 'aristotle_auto_budget_recovery',
    AUTO_SCROLL: 'aristotle_autoscroll_enabled',
    SCROLL_INTERVAL: 'aristotle_scroll_interval',
    LAST_SENT: 'aristotle_last_sent_message',
  });

  const ActionTypes = Object.freeze({
    HYDRATE_STATE: 'HYDRATE_STATE',
    TOGGLE_RUNNER: 'TOGGLE_RUNNER',
    SET_RUNNER_ACTIVE: 'SET_RUNNER_ACTIVE',
    TOGGLE_BUDGET_RECOVERY: 'TOGGLE_BUDGET_RECOVERY',
    SET_BUDGET_RECOVERY: 'SET_BUDGET_RECOVERY',
    SET_AUTO_SCROLL: 'SET_AUTO_SCROLL',
    SET_SCROLL_INTERVAL: 'SET_SCROLL_INTERVAL',
    ENQUEUE_MESSAGE: 'ENQUEUE_MESSAGE',
    UPDATE_MESSAGE: 'UPDATE_MESSAGE',
    REMOVE_MESSAGE: 'REMOVE_MESSAGE',
    CLEAR_QUEUE: 'CLEAR_QUEUE',
    POP_QUEUE: 'POP_QUEUE',
    SET_LAST_SENT: 'SET_LAST_SENT',
    SET_COMPOSER_DRAFT: 'SET_COMPOSER_DRAFT',
    SET_BUSY_STATE: 'SET_BUSY_STATE',
    SET_RECOVERING_BUDGET: 'SET_RECOVERING_BUDGET',
    SET_LAST_SCROLL_TIME: 'SET_LAST_SCROLL_TIME',
    SET_FALLBACK_KEY: 'SET_FALLBACK_KEY',
    OPEN_EDIT_MODAL: 'OPEN_EDIT_MODAL',
    CLOSE_EDIT_MODAL: 'CLOSE_EDIT_MODAL',
  });

  const INITIAL_STATE = Object.freeze({
    queue: Object.freeze([]),
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
    editingIndex: null,
  });

  const rootReducer = (state = INITIAL_STATE, action) => {
    switch (action.type) {
      case ActionTypes.HYDRATE_STATE:
        return Object.freeze({ ...state, ...action.payload });

      case ActionTypes.TOGGLE_RUNNER:
        return Object.freeze({ ...state, isRunnerActive: !state.isRunnerActive });

      case ActionTypes.SET_RUNNER_ACTIVE:
        return Object.freeze({ ...state, isRunnerActive: Boolean(action.payload) });

      case ActionTypes.TOGGLE_BUDGET_RECOVERY:
        return Object.freeze({ ...state, autoBudgetRecoveryEnabled: !state.autoBudgetRecoveryEnabled });

      case ActionTypes.SET_BUDGET_RECOVERY:
        return Object.freeze({ ...state, autoBudgetRecoveryEnabled: Boolean(action.payload) });

      case ActionTypes.SET_AUTO_SCROLL:
        return Object.freeze({ ...state, autoScrollEnabled: Boolean(action.payload) });

      case ActionTypes.SET_SCROLL_INTERVAL:
        return Object.freeze({ ...state, scrollIntervalSeconds: Number(action.payload) || 5 });

      case ActionTypes.ENQUEUE_MESSAGE:
        return trim(action.payload)
          ? Object.freeze({ ...state, queue: append(trim(action.payload), state.queue) })
          : state;

      case ActionTypes.UPDATE_MESSAGE:
        return Object.freeze({
          ...state,
          queue: updateAt(action.payload.index, trim(action.payload.text), state.queue),
        });

      case ActionTypes.REMOVE_MESSAGE:
        return Object.freeze({
          ...state,
          queue: removeAt(action.payload, state.queue),
        });

      case ActionTypes.CLEAR_QUEUE:
        return Object.freeze({ ...state, queue: Object.freeze([]), isRunnerActive: false });

      case ActionTypes.POP_QUEUE: {
        const [, ...rest] = state.queue;
        return Object.freeze({ ...state, queue: rest });
      }

      case ActionTypes.SET_LAST_SENT:
        return Object.freeze({ ...state, lastSentMessage: action.payload, composerDraft: '' });

      case ActionTypes.SET_COMPOSER_DRAFT:
        return Object.freeze({ ...state, composerDraft: action.payload });

      case ActionTypes.SET_BUSY_STATE:
        return Object.freeze({
          ...state,
          isBusy: Boolean(action.payload.isBusy),
          handledFallbackKey: action.payload.handledFallbackKey ?? state.handledFallbackKey,
        });

      case ActionTypes.SET_RECOVERING_BUDGET:
        return Object.freeze({ ...state, isRecoveringBudget: Boolean(action.payload) });

      case ActionTypes.SET_LAST_SCROLL_TIME:
        return Object.freeze({ ...state, lastScrollTimestamp: Number(action.payload) });

      case ActionTypes.SET_FALLBACK_KEY:
        return Object.freeze({ ...state, handledFallbackKey: String(action.payload) });

      case ActionTypes.OPEN_EDIT_MODAL:
        return Object.freeze({ ...state, editingIndex: Number(action.payload) });

      case ActionTypes.CLOSE_EDIT_MODAL:
        return Object.freeze({ ...state, editingIndex: null });

      default:
        return state;
    }
  };

  const createStore = (reducer, initialState, subscriber = () => { }) => {
    let currentState = Object.freeze({ ...initialState });
    return {
      getState: () => currentState,
      dispatch: (action) => {
        const nextState = Object.freeze(reducer(currentState, action));
        if (nextState !== currentState) {
          currentState = nextState;
          subscriber(currentState, action);
        }
        return action;
      },
    };
  };

  // =========================================================================
  // 5. Side-Effecting Drivers (I/O Boundary)
  // =========================================================================

  const persistToStorage = (state) => {
    const payload = {
      [STORAGE_KEYS.QUEUE]: state.queue,
      [STORAGE_KEYS.RUNNER_ACTIVE]: state.isRunnerActive,
      [STORAGE_KEYS.BUDGET_RECOVERY]: state.autoBudgetRecoveryEnabled,
      [STORAGE_KEYS.AUTO_SCROLL]: state.autoScrollEnabled,
      [STORAGE_KEYS.SCROLL_INTERVAL]: state.scrollIntervalSeconds,
      [STORAGE_KEYS.LAST_SENT]: state.lastSentMessage,
    };

    if (typeof chrome !== 'undefined' && chrome?.storage?.local) {
      chrome.storage.local.set(payload).catch(() => { });
    }
    try {
      window.localStorage.setItem('aristotle_aq_state', JSON.stringify(payload));
    } catch (_) { }
  };

  const setNativeComposerValue = (textarea, value) => {
    textarea.focus();
    const valueSetter = Object.getOwnPropertyDescriptor(textarea, 'value')?.set;
    const protoSetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(textarea), 'value')?.set;

    if (protoSetter && valueSetter !== protoSetter) {
      protoSetter.call(textarea, value);
    } else if (valueSetter) {
      valueSetter.call(textarea, value);
    } else {
      textarea.value = value;
    }

    textarea.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    textarea.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, data: value }));
    textarea.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
  };

  const triggerComposerSubmit = (textarea) => {
    const sendBtn = selectSendButton();
    if (sendBtn && !sendBtn.disabled && !sendBtn.hasAttribute('data-disabled')) {
      sendBtn.click();
      return true;
    }

    textarea.focus();
    const eventInit = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
    textarea.dispatchEvent(new KeyboardEvent('keydown', eventInit));
    textarea.dispatchEvent(new KeyboardEvent('keypress', eventInit));
    textarea.dispatchEvent(new KeyboardEvent('keyup', eventInit));
    return false;
  };

  const executePromptSubmission = async (textarea, message) => {
    textarea.focus();
    setNativeComposerValue(textarea, message);
    await sleep(400);

    const sendBtn = selectSendButton();
    if (sendBtn && (sendBtn.disabled || sendBtn.hasAttribute('data-disabled'))) {
      textarea.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      await sleep(300);
    }
    triggerComposerSubmit(textarea);
  };

  const performFeedScroll = () => {
    const container = selectScrollContainer();
    if (container) container.scrollTop = container.scrollHeight;
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  };

  // =========================================================================
  // 6. Declarative UI Component Templates & Binding
  // =========================================================================

  const buildModalHTML = () => `
    <div id="aristotle-queue-header">
      <h3><span id="aristotle-status-dot" class="idle"></span> Aristotle Auto-Queue</h3>
      <span id="aq-toggle-min" style="cursor:pointer;color:#71717a;">_</span>
    </div>
    <div id="aristotle-queue-body">
      <button id="aq-btn-toggle-budget" class="aq-btn aq-btn-big aq-btn-primary">
        ▶ Start autosubmit "continue" on "out of budget"
      </button>

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

      <div class="aq-card">
        <div class="aq-card-header">
          <span>Last User Task (Confirmed)</span>
          <button id="aq-btn-rescan" class="aq-link-btn" title="Scan feed for last user prompt">🔄 Scan Feed</button>
        </div>
        <textarea id="aq-confirmed-prompt" class="aq-mono-area" rows="3" placeholder="Scanning feed or waiting for input..."></textarea>
        <div class="aq-card-hint">Used for auto-submitting continuation when out of budget.</div>
      </div>

      <textarea id="aristotle-input-area" placeholder="Paste full Markdown message here..."></textarea>
      <div class="aq-btn-row">
        <button id="aq-btn-add" class="aq-btn aq-btn-secondary">+ Add Message to Queue</button>
        <button id="aq-btn-clear" class="aq-btn aq-btn-danger">Clear</button>
      </div>

      <div style="font-weight:600; font-size:11px; text-transform:uppercase; color:#71717a;">
        Queue (<span id="aq-count">0</span>)
      </div>
      <div id="aq-queue-list-container">
        <div id="aq-queue-list"></div>
      </div>

      <div id="aq-log">Status: Idle</div>
    </div>
  `;

  const buildEditModalHTML = () => `
    <div class="aq-edit-dialog">
      <div class="aq-edit-header">
        <div class="aq-edit-title-group">
          <span class="aq-edit-title">Edit Queued Message</span>
          <span id="aq-edit-badge" class="aq-badge">#1</span>
        </div>
        <div class="aq-edit-meta">
          <span id="aq-edit-stats">0 chars | 0 lines</span>
          <button id="aq-edit-close" class="aq-icon-btn" title="Close (Esc)">&times;</button>
        </div>
      </div>
      <div class="aq-edit-body">
        <textarea id="aq-edit-textarea" class="aq-edit-textarea" placeholder="Edit Markdown prompt..."></textarea>
      </div>
      <div class="aq-edit-footer">
        <div class="aq-edit-shortcuts">
          <span><kbd>Ctrl</kbd>+<kbd>Enter</kbd> to save</span>
          <span><kbd>Esc</kbd> to cancel</span>
        </div>
        <div class="aq-edit-actions">
          <button id="aq-edit-cancel" class="aq-btn aq-btn-secondary">Cancel</button>
          <button id="aq-edit-save" class="aq-btn aq-btn-primary">Save Changes</button>
        </div>
      </div>
    </div>
  `;

  const mountElements = () => {
    const modal = document.createElement('div');
    modal.id = 'aristotle-queue-modal';
    modal.innerHTML = buildModalHTML();
    document.body.appendChild(modal);

    const editOverlay = document.createElement('div');
    editOverlay.id = 'aq-edit-overlay';
    editOverlay.className = 'aq-overlay';
    editOverlay.style.display = 'none';
    editOverlay.innerHTML = buildEditModalHTML();
    document.body.appendChild(editOverlay);

    return { modal, editOverlay };
  };

  const setupDraggable = (modal) => {
    let offset = null;
    const header = query('#aristotle-queue-header', modal);
    const toggleMin = query('#aq-toggle-min', modal);

    header.addEventListener('mousedown', (e) => {
      if (e.target === toggleMin) return;
      offset = { x: e.clientX - modal.offsetLeft, y: e.clientY - modal.offsetTop };
    });

    window.addEventListener('mousemove', (e) => {
      if (!offset) return;
      modal.style.left = `${Math.max(10, e.clientX - offset.x)}px`;
      modal.style.top = `${Math.max(10, e.clientY - offset.y)}px`;
      modal.style.right = 'auto';
    });

    window.addEventListener('mouseup', () => {
      offset = null;
    });
  };

  const renderQueueList = (container, countEl, queue, dispatch) => {
    countEl.textContent = queue.length;
    if (queue.length === 0) {
      container.innerHTML = `<div style="padding: 10px; color: #52525b; text-align: center;">Queue is empty</div>`;
      return;
    }

    container.innerHTML = queue
      .map(
        (text, idx) => `
          <div class="aq-item" data-idx="${idx}">
            <div class="aq-item-header">
              <span style="color:#71717a; font-family:monospace;">#${idx + 1} (${text.length} chars)</span>
              <div style="display:flex; gap:8px; align-items:center;">
                <span class="aq-item-edit" data-idx="${idx}" title="Edit in modal">edit</span>
                <span class="aq-item-toggle" data-idx="${idx}">expand</span>
                <span class="aq-item-remove" data-idx="${idx}">&times;</span>
              </div>
            </div>
            <div class="aq-item-text collapsed" id="aq-text-${idx}">${escapeHtml(text)}</div>
          </div>
        `
      )
      .join('');

    queryAll('.aq-item-edit', container).forEach((btn) => {
      btn.addEventListener('click', (e) => {
        dispatch({ type: ActionTypes.OPEN_EDIT_MODAL, payload: parseInt(e.currentTarget.dataset.idx, 10) });
      });
    });

    queryAll('.aq-item-remove', container).forEach((btn) => {
      btn.addEventListener('click', (e) => {
        dispatch({ type: ActionTypes.REMOVE_MESSAGE, payload: parseInt(e.currentTarget.dataset.idx, 10) });
      });
    });

    queryAll('.aq-item-toggle', container).forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const textEl = query(`#aq-text-${e.currentTarget.dataset.idx}`, container);
        const isCollapsed = textEl.classList.toggle('collapsed');
        e.currentTarget.textContent = isCollapsed ? 'expand' : 'collapse';
      });
    });
  };

  const bindUI = (elements, store) => {
    const { modal, editOverlay } = elements;
    const { dispatch } = store;

    // Element queries
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

    // Edit modal elements
    const editBadge = query('#aq-edit-badge', editOverlay);
    const editStats = query('#aq-edit-stats', editOverlay);
    const editTextarea = query('#aq-edit-textarea', editOverlay);
    const editSaveBtn = query('#aq-edit-save', editOverlay);
    const editCancelBtn = query('#aq-edit-cancel', editOverlay);
    const editCloseBtn = query('#aq-edit-close', editOverlay);

    setupDraggable(modal);

    const setLog = (text, statusType = 'idle') => {
      logBox.textContent = `Status: ${text}`;
      statusDot.className = statusType;
    };

    const updateBudgetButtonUI = (enabled) => {
      budgetToggleBtn.textContent = enabled
        ? '⏸ Pause autosubmit "continue" on "out of budget"'
        : '▶ Start autosubmit "continue" on "out of budget"';
      budgetToggleBtn.classList.toggle('aq-btn-danger', enabled);
      budgetToggleBtn.classList.toggle('aq-btn-primary', !enabled);
    };

    const updateRunnerButtonUI = (active) => {
      startBtn.textContent = active ? '⏸ Pause Auto-Runner' : '▶ Start Auto-Runner';
      startBtn.classList.toggle('aq-btn-danger', active);
      startBtn.classList.toggle('aq-btn-secondary', !active);
    };

    const updateEditStats = (text = '') => {
      const { chars, lines } = calculateStats(text);
      editStats.textContent = `${chars} chars | ${lines} lines`;
    };

    const openEditDialog = (index) => {
      const content = store.getState().queue[index] || '';
      editBadge.textContent = `#${index + 1}`;
      editTextarea.value = content;
      updateEditStats(content);
      editOverlay.style.display = 'flex';
      setTimeout(() => editTextarea.focus(), 50);
    };

    const closeEditDialog = () => {
      editOverlay.style.display = 'none';
      dispatch({ type: ActionTypes.CLOSE_EDIT_MODAL });
    };

    const commitEditDialog = () => {
      const { editingIndex } = store.getState();
      if (editingIndex !== null) {
        dispatch({
          type: ActionTypes.UPDATE_MESSAGE,
          payload: { index: editingIndex, text: editTextarea.value },
        });
      }
      closeEditDialog();
    };

    // Listeners
    editTextarea.addEventListener('input', () => updateEditStats(editTextarea.value));
    editSaveBtn.addEventListener('click', commitEditDialog);
    editCancelBtn.addEventListener('click', closeEditDialog);
    editCloseBtn.addEventListener('click', closeEditDialog);

    window.addEventListener('keydown', (e) => {
      if (editOverlay.style.display === 'flex') {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeEditDialog();
        } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          commitEditDialog();
        }
      }
    });

    confirmedPromptInput.addEventListener('input', () => {
      dispatch({ type: ActionTypes.SET_LAST_SENT, payload: confirmedPromptInput.value.trim() });
    });

    const triggerScan = async () => {
      setLog('Scanning feed for last user prompt...', 'waiting');
      const detected = await findLastPromptWithFallbackScroll();
      if (detected && isSubstantivePrompt(detected)) {
        confirmedPromptInput.value = detected;
        dispatch({ type: ActionTypes.SET_LAST_SENT, payload: detected });
        setLog('Found last user task. Confirmed.', 'idle');
      } else {
        setLog('No user task found yet. Type it above or scan again.', 'idle');
      }
    };

    rescanBtn.addEventListener('click', triggerScan);

    budgetToggleBtn.addEventListener('click', () => {
      dispatch({ type: ActionTypes.TOGGLE_BUDGET_RECOVERY });
      const enabled = store.getState().autoBudgetRecoveryEnabled;
      updateBudgetButtonUI(enabled);
      if (enabled) {
        triggerScan();
        setLog('Autosubmit on Out of Budget: ENABLED', 'active');
      } else {
        setLog('Autosubmit on Out of Budget: PAUSED', 'idle');
      }
    });

    startBtn.addEventListener('click', () => {
      const state = store.getState();
      if (!state.isRunnerActive && state.queue.length === 0) {
        alert('Queue is empty! Add a message first.');
        return;
      }
      dispatch({ type: ActionTypes.TOGGLE_RUNNER });
      const active = store.getState().isRunnerActive;
      updateRunnerButtonUI(active);
      setLog(active ? 'Auto-Runner started' : 'Auto-Runner paused', active ? 'active' : 'idle');
    });

    addBtn.addEventListener('click', () => {
      const text = inputArea.value.trim();
      if (!text) return;
      dispatch({ type: ActionTypes.ENQUEUE_MESSAGE, payload: text });
      inputArea.value = '';
    });

    clearBtn.addEventListener('click', () => {
      const { isRunnerActive } = store.getState();
      if (isRunnerActive && !confirm('Pause runner and clear queue?')) return;
      dispatch({ type: ActionTypes.CLEAR_QUEUE });
      updateRunnerButtonUI(false);
    });

    autoScrollCheckbox.addEventListener('change', () => {
      dispatch({ type: ActionTypes.SET_AUTO_SCROLL, payload: autoScrollCheckbox.checked });
    });

    scrollIntervalInput.addEventListener('change', () => {
      const val = parseInt(scrollIntervalInput.value, 10);
      dispatch({ type: ActionTypes.SET_SCROLL_INTERVAL, payload: !isNaN(val) && val > 0 ? val : 5 });
    });

    toggleMin.addEventListener('click', () => {
      const isHidden = body.style.display === 'none';
      body.style.display = isHidden ? 'flex' : 'none';
      toggleMin.textContent = isHidden ? '_' : '□';
    });

    return {
      setLog,
      renderQueue: (q) => renderQueueList(queueList, queueCount, q, dispatch),
      updateBudgetButtonUI,
      updateRunnerButtonUI,
      triggerScan,
      openEditDialog,
      confirmedPromptInput,
      autoScrollCheckbox,
      scrollIntervalInput,
    };
  };

  const registerInputObservers = (store, onCommit) => {
    document.addEventListener(
      'input',
      (e) => {
        const textarea = selectComposerTextarea();
        if (e.target === textarea && textarea.value.trim()) {
          store.dispatch({ type: ActionTypes.SET_COMPOSER_DRAFT, payload: textarea.value.trim() });
        }
      },
      true
    );

    const handleCommit = () => {
      const textarea = selectComposerTextarea();
      const text = textarea?.value?.trim() || store.getState().composerDraft;
      if (text && isSubstantivePrompt(text)) {
        store.dispatch({ type: ActionTypes.SET_LAST_SENT, payload: text });
        onCommit(text);
      }
    };

    document.addEventListener(
      'keydown',
      (e) => {
        if (e.target === selectComposerTextarea() && e.key === 'Enter' && !e.shiftKey) {
          handleCommit();
        }
      },
      true
    );

    document.addEventListener(
      'click',
      (e) => {
        const sendBtn = selectSendButton();
        if (sendBtn && (sendBtn === e.target || sendBtn.contains(e.target))) {
          handleCommit();
        }
      },
      true
    );
  };

  // =========================================================================
  // 7. Functional Reactive Loop & Evaluators
  // =========================================================================

  const evaluateBusyPhase = async (state, store, ui) => {
    const now = Date.now();
    if (state.autoScrollEnabled && now - state.lastScrollTimestamp >= state.scrollIntervalSeconds * 1000) {
      performFeedScroll();
      store.dispatch({ type: ActionTypes.SET_LAST_SCROLL_TIME, payload: now });
    }

    if (!state.isBusy) {
      document.querySelectorAll('[data-aq-handled]').forEach((el) => {
        delete el.dataset.aqHandled;
      });
      store.dispatch({
        type: ActionTypes.SET_BUSY_STATE,
        payload: { isBusy: true, handledFallbackKey: '' },
      });
      ui.setLog(state.autoScrollEnabled ? 'Aristotle working... auto-scrolling' : 'Aristotle working...', 'waiting');
    }
  };

  const evaluateIdleTransition = async (state, store, ui) => {
    store.dispatch({ type: ActionTypes.SET_BUSY_STATE, payload: { isBusy: false } });
    ui.setLog('Task stopped. Checking outcome...', 'waiting');
    if (state.autoScrollEnabled) {
      performFeedScroll();
      await sleep(1200);
      performFeedScroll();
    } else {
      await sleep(1200);
    }
  };

  const evaluateBudgetRecovery = async (state, store, ui, textarea) => {
    const execInfo = selectExecutionStatus();
    const isBudgetExhausted = isOutOfBudgetStatus(execInfo.status);
    const fallbackKey = `${execInfo.status}_${state.lastSentMessage}`;
    const isAlreadyHandled = execInfo.element
      ? execInfo.element.dataset.aqHandled === 'true'
      : state.handledFallbackKey === fallbackKey;

    if (!state.autoBudgetRecoveryEnabled || !isBudgetExhausted || isAlreadyHandled || state.isRecoveringBudget) {
      return false;
    }

    // Safety Guard: Textarea already contains non-empty user draft -> Pause!
    const currentComposerText = trim(textarea.value);
    if (currentComposerText.length > 0) {
      store.dispatch({ type: ActionTypes.SET_BUDGET_RECOVERY, payload: false });
      ui.updateBudgetButtonUI(false);
      ui.setLog('Composer contains unsent text! Autosubmit on Out of Budget PAUSED.', 'idle');
      return true; // Stop recovery evaluation, leave task unhandled
    }

    const mode = selectComposerMode();
    if (mode === 'ask') {
      if (execInfo.element) execInfo.element.dataset.aqHandled = 'true';
      else store.dispatch({ type: ActionTypes.SET_FALLBACK_KEY, payload: fallbackKey });
      ui.setLog('OUT OF BUDGET detected, but composer is in ASK mode. Continuation skipped.', 'idle');
      return true;
    }

    // Flag handled
    if (execInfo.element) execInfo.element.dataset.aqHandled = 'true';
    else store.dispatch({ type: ActionTypes.SET_FALLBACK_KEY, payload: fallbackKey });

    store.dispatch({ type: ActionTypes.SET_RECOVERING_BUDGET, payload: true });
    ui.setLog('OUT OF BUDGET detected! Submitting continuation...', 'waiting');
    await sleep(800);

    const basePrompt = state.lastSentMessage.trim() || state.composerDraft.trim();
    const continuationPrompt = formatContinuationMessage(basePrompt);

    await executePromptSubmission(textarea, continuationPrompt);

    store.dispatch({ type: ActionTypes.SET_LAST_SENT, payload: continuationPrompt });
    store.dispatch({ type: ActionTypes.SET_RECOVERING_BUDGET, payload: false });
    ui.confirmedPromptInput.value = continuationPrompt;

    let attempts = 0;
    while (attempts++ < 20) {
      await sleep(400);
      if (selectStopButton()) {
        store.dispatch({ type: ActionTypes.SET_BUSY_STATE, payload: { isBusy: true } });
        break;
      }
    }

    ui.setLog('Continuation active. Proving/Solving...', 'waiting');
    return true;
  };

  const evaluateQueueRunner = async (state, store, ui, textarea) => {
    if (!state.isRunnerActive) return;

    if (state.queue.length === 0) {
      ui.setLog('All tasks in queue completed!', 'active');
      store.dispatch({ type: ActionTypes.SET_RUNNER_ACTIVE, payload: false });
      ui.updateRunnerButtonUI(false);
      return;
    }

    const isReady = textarea && !textarea.disabled && !selectStopButton();
    if (!isReady) return;

    // Safety Guard: Pause runner if composer has manual draft
    const currentComposerText = trim(textarea.value);
    if (currentComposerText.length > 0) {
      store.dispatch({ type: ActionTypes.SET_RUNNER_ACTIVE, payload: false });
      ui.updateRunnerButtonUI(false);
      ui.setLog('Composer contains unsent text! Auto-Runner PAUSED.', 'idle');
      return;
    }

    const [nextTask] = state.queue;
    ui.setLog(`Typing queued task (${state.queue.length} in queue)...`, 'active');
    await executePromptSubmission(textarea, nextTask);

    store.dispatch({ type: ActionTypes.POP_QUEUE });
    store.dispatch({ type: ActionTypes.SET_LAST_SENT, payload: nextTask });
    ui.confirmedPromptInput.value = nextTask;

    let attempts = 0;
    while (attempts++ < 20) {
      await sleep(400);
      if (selectStopButton()) {
        store.dispatch({ type: ActionTypes.SET_BUSY_STATE, payload: { isBusy: true } });
        break;
      }
    }
  };

  const runAutomationTick = async (store, ui) => {
    const state = store.getState();
    const textarea = selectComposerTextarea();
    const isBusy = Boolean(selectStopButton());

    // 1. Aristotle Active
    if (isBusy) {
      await evaluateBusyPhase(state, store, ui);
      return;
    }

    // 2. Transition from Busy -> Idle
    if (state.isBusy && !isBusy) {
      await evaluateIdleTransition(state, store, ui);
      return;
    }

    // 3. Out of Budget Recovery Check
    if (textarea && !textarea.disabled) {
      const didRecover = await evaluateBudgetRecovery(state, store, ui, textarea);
      if (didRecover) return;
    }

    // 4. Queue Runner Step Check
    if (textarea && !textarea.disabled) {
      await evaluateQueueRunner(state, store, ui, textarea);
    }
  };

  const startContinuousLoop = (store, ui) => {
    const loop = async () => {
      try {
        await runAutomationTick(store, ui);
      } catch (err) {
        console.error('[Aristotle Auto-Queue] Step error:', err);
      }
      setTimeout(loop, 1000);
    };
    loop();
  };

  // =========================================================================
  // 8. Bootstrap & Hydration
  // =========================================================================

  const hydrateState = (raw = {}) => {
    const autoScroll = typeof raw[STORAGE_KEYS.AUTO_SCROLL] === 'boolean' ? raw[STORAGE_KEYS.AUTO_SCROLL] : false;
    const autoBudget = typeof raw[STORAGE_KEYS.BUDGET_RECOVERY] === 'boolean' ? raw[STORAGE_KEYS.BUDGET_RECOVERY] : true;
    const runnerActive = typeof raw[STORAGE_KEYS.RUNNER_ACTIVE] === 'boolean' ? raw[STORAGE_KEYS.RUNNER_ACTIVE] : false;
    const storedLastPrompt = raw[STORAGE_KEYS.LAST_SENT] || '';
    const hasSubstantive = isSubstantivePrompt(storedLastPrompt);
    const queue = Array.isArray(raw[STORAGE_KEYS.QUEUE]) ? raw[STORAGE_KEYS.QUEUE] : [];
    const interval = raw[STORAGE_KEYS.SCROLL_INTERVAL] || 5;

    return {
      queue: Object.freeze(queue),
      scrollIntervalSeconds: interval,
      autoScrollEnabled: autoScroll,
      autoBudgetRecoveryEnabled: autoBudget,
      isRunnerActive: runnerActive && queue.length > 0,
      lastSentMessage: hasSubstantive ? storedLastPrompt : '',
    };
  };

  const init = () => {
    const elements = mountElements();
    let ui = null;

    const store = createStore(rootReducer, INITIAL_STATE, (nextState, action) => {
      persistToStorage(nextState);
      if (ui) {
        // Reactive UI updates on specific action dispatches
        if ([ActionTypes.ENQUEUE_MESSAGE, ActionTypes.UPDATE_MESSAGE, ActionTypes.REMOVE_MESSAGE, ActionTypes.CLEAR_QUEUE, ActionTypes.POP_QUEUE, ActionTypes.HYDRATE_STATE].includes(action.type)) {
          ui.renderQueue(nextState.queue);
        }
        if (action.type === ActionTypes.OPEN_EDIT_MODAL) {
          ui.openEditDialog(action.payload);
        }
      }
    });

    ui = bindUI(elements, store);

    registerInputObservers(store, (newPrompt) => {
      ui.confirmedPromptInput.value = newPrompt;
    });

    const bootWithData = async (data) => {
      const hydrated = hydrateState(data);
      store.dispatch({ type: ActionTypes.HYDRATE_STATE, payload: hydrated });

      ui.autoScrollCheckbox.checked = hydrated.autoScrollEnabled;
      ui.scrollIntervalInput.value = hydrated.scrollIntervalSeconds;
      ui.updateBudgetButtonUI(hydrated.autoBudgetRecoveryEnabled);
      ui.updateRunnerButtonUI(hydrated.isRunnerActive);
      ui.renderQueue(hydrated.queue);

      if (hydrated.lastSentMessage) {
        ui.confirmedPromptInput.value = hydrated.lastSentMessage;
      }

      if (hydrated.autoBudgetRecoveryEnabled) {
        await sleep(500);
        await ui.triggerScan();
      }

      startContinuousLoop(store, ui);
    };

    if (typeof chrome !== 'undefined' && chrome?.storage?.local) {
      chrome.storage.local.get(Object.values(STORAGE_KEYS), (res) => {
        if (chrome.runtime.lastError || !res || Object.keys(res).length === 0) {
          try {
            const raw = window.localStorage.getItem('aristotle_aq_state');
            bootWithData(raw ? JSON.parse(raw) : {});
          } catch (_) {
            bootWithData({});
          }
        } else {
          bootWithData(res);
        }
      });
    } else {
      try {
        const raw = window.localStorage.getItem('aristotle_aq_state');
        bootWithData(raw ? JSON.parse(raw) : {});
      } catch (_) {
        bootWithData({});
      }
    }
  };

  init();
})();
