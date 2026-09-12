(function () {
  'use strict';

  // --- State Variables ---
  let queue = [];
  let isRunning = false;
  let scrollIntervalSeconds = 5;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // --- Storage Helpers ---
  function saveState() {
    if (chrome?.storage?.local) {
      chrome.storage.local.set({
        aristotle_queue: queue,
        aristotle_scroll_interval: scrollIntervalSeconds,
      });
    }
  }

  function loadState(cb) {
    if (chrome?.storage?.local) {
      chrome.storage.local.get(['aristotle_queue', 'aristotle_scroll_interval'], (res) => {
        if (Array.isArray(res.aristotle_queue)) queue = res.aristotle_queue;
        if (res.aristotle_scroll_interval) scrollIntervalSeconds = res.aristotle_scroll_interval;
        cb();
      });
    } else {
      cb();
    }
  }

  // --- Scroll Logic ---
  function getScrollContainer() {
    let container = document.querySelector('[data-scrollable]');
    if (!container) {
      const feed = document.querySelector('[data-feed-group]');
      if (feed) {
        let p = feed.parentElement;
        while (p && p !== document.body) {
          if (p.scrollHeight > p.clientHeight && p.clientHeight > 0) {
            container = p;
            break;
          }
          p = p.parentElement;
        }
      }
    }
    return container || document.documentElement || document.body;
  }

  function scrollFeedToBottom() {
    const container = getScrollContainer();
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  }

  // --- Element Matchers ---
  function getComposerTextarea() {
    return document.querySelector('textarea[data-testid="composer.textarea"]');
  }

  function getStopButton() {
    return document.querySelector('button[data-testid="composer.stop"]');
  }

  function getSendButton() {
    return (
      document.querySelector('button[data-testid="composer.send"]') ||
      document.querySelector('button[data-testid="composer.submit"]') ||
      document.querySelector('button[aria-label="Send"], button[aria-label="Submit"]')
    );
  }

  // Inspect the top status strip
  function getLastExecutionStatus() {
    const statusBanners = document.querySelectorAll(
      'div.border-border span.font-mono.uppercase, div[class*="border-b"] span[class*="font-mono"][class*="uppercase"]'
    );
    if (statusBanners.length > 0) {
      const last = statusBanners[statusBanners.length - 1];
      return (last.textContent || '').trim().toUpperCase();
    }

    const allText = document.body.innerText.toUpperCase();
    if (allText.includes('OUT OF BUDGET')) return 'OUT OF BUDGET';
    if (allText.includes('COMPLETED')) return 'COMPLETED';

    return 'UNKNOWN';
  }

  // React synthetic input setter
  function setNativeValue(element, value) {
    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

    if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else if (valueSetter) {
      valueSetter.call(element, value);
    } else {
      element.value = value;
    }

    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function triggerSubmit(textarea) {
    const sendBtn = getSendButton();
    if (sendBtn && !sendBtn.disabled) {
      sendBtn.click();
      return true;
    }

    textarea.focus();
    const eventParams = {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true,
      cancelable: true,
    };
    textarea.dispatchEvent(new KeyboardEvent('keydown', eventParams));
    textarea.dispatchEvent(new KeyboardEvent('keypress', eventParams));
    textarea.dispatchEvent(new KeyboardEvent('keyup', eventParams));
    return true;
  }

  // --- Modal Injection ---
  const modal = document.createElement('div');
  modal.id = 'aristotle-queue-modal';
  modal.innerHTML = `
    <div id="aristotle-queue-header">
      <h3><span id="aristotle-status-dot" class="idle"></span> Aristotle Auto-Queue</h3>
      <span id="aq-toggle-min" style="cursor:pointer;color:#71717a;">_</span>
    </div>
    <div id="aristotle-queue-body">
      <textarea id="aristotle-input-area" placeholder="Paste full Markdown message here..."></textarea>

      <div class="aq-btn-row">
        <button id="aq-btn-add" class="aq-btn aq-btn-secondary">+ Add Message to Queue</button>
        <button id="aq-btn-clear" class="aq-btn aq-btn-danger">Clear</button>
      </div>

      <div class="aq-setting-row">
        <span>Auto-scroll down interval:</span>
        <div>
          <input type="number" id="aq-scroll-interval" class="aq-number-input" value="5" min="1" max="60" /> s
        </div>
      </div>

      <div style="font-weight:600; font-size:11px; text-transform:uppercase; color:#71717a;">
        Queue (<span id="aq-count">0</span>)
      </div>
      <div id="aq-queue-list-container">
        <div id="aq-queue-list"></div>
      </div>

      <div class="aq-btn-row">
        <button id="aq-btn-start" class="aq-btn aq-btn-primary">▶ Start Auto-Runner</button>
      </div>
      <div id="aq-log">Status: Idle</div>
    </div>
  `;

  document.body.appendChild(modal);

  // --- UI Elements ---
  const inputArea = modal.querySelector('#aristotle-input-area');
  const addBtn = modal.querySelector('#aq-btn-add');
  const clearBtn = modal.querySelector('#aq-btn-clear');
  const startBtn = modal.querySelector('#aq-btn-start');
  const queueList = modal.querySelector('#aq-queue-list');
  const queueCount = modal.querySelector('#aq-count');
  const statusDot = modal.querySelector('#aristotle-status-dot');
  const logBox = modal.querySelector('#aq-log');
  const body = modal.querySelector('#aristotle-queue-body');
  const toggleMin = modal.querySelector('#aq-toggle-min');
  const scrollIntervalInput = modal.querySelector('#aq-scroll-interval');

  scrollIntervalInput.addEventListener('change', () => {
    const val = parseInt(scrollIntervalInput.value, 10);
    scrollIntervalSeconds = !isNaN(val) && val > 0 ? val : 5;
    saveState();
  });

  // Minimize / Expand
  toggleMin.addEventListener('click', () => {
    if (body.style.display === 'none') {
      body.style.display = 'flex';
      toggleMin.textContent = '_';
    } else {
      body.style.display = 'none';
      toggleMin.textContent = '□';
    }
  });

  // Dragging Header
  let isDragging = false, dragX = 0, dragY = 0;
  modal.querySelector('#aristotle-queue-header').addEventListener('mousedown', (e) => {
    if (e.target === toggleMin) return;
    isDragging = true;
    dragX = e.clientX - modal.offsetLeft;
    dragY = e.clientY - modal.offsetTop;
  });
  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    modal.style.left = `${Math.max(10, e.clientX - dragX)}px`;
    modal.style.top = `${Math.max(10, e.clientY - dragY)}px`;
    modal.style.right = 'auto';
  });
  window.addEventListener('mouseup', () => { isDragging = false; });

  function setLog(text, state = 'idle') {
    logBox.textContent = `Status: ${text}`;
    statusDot.className = state;
  }

  function renderQueue() {
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

    queueList.querySelectorAll('.aq-item-remove').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        queue.splice(idx, 1);
        saveState();
        renderQueue();
      });
    });

    queueList.querySelectorAll('.aq-item-toggle').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const idx = e.target.dataset.idx;
        const textEl = document.getElementById(`aq-text-${idx}`);
        if (textEl.classList.contains('collapsed')) {
          textEl.classList.remove('collapsed');
          e.target.textContent = 'collapse';
        } else {
          textEl.classList.add('collapsed');
          e.target.textContent = 'expand';
        }
      });
    });
  }

  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    }[m]));
  }

  // Add WHOLE Markdown Text to Queue as 1 Item
  addBtn.addEventListener('click', () => {
    const raw = inputArea.value.trim();
    if (!raw) return;

    queue.push(raw);
    inputArea.value = '';
    saveState();
    renderQueue();
  });

  clearBtn.addEventListener('click', () => {
    if (isRunning && !confirm('Stop runner and clear queue?')) return;
    if (isRunning) stopRunner();
    queue = [];
    saveState();
    renderQueue();
  });

  startBtn.addEventListener('click', () => {
    if (isRunning) {
      stopRunner();
    } else {
      startRunner();
    }
  });

  function startRunner() {
    if (queue.length === 0) {
      alert('Queue is empty! Add a message first.');
      return;
    }
    isRunning = true;
    startBtn.textContent = '⏸ Pause Runner';
    startBtn.classList.remove('aq-btn-primary');
    startBtn.classList.add('aq-btn-danger');
    runLoop();
  }

  function stopRunner() {
    isRunning = false;
    startBtn.textContent = '▶ Start Auto-Runner';
    startBtn.classList.remove('aq-btn-danger');
    startBtn.classList.add('aq-btn-primary');
    setLog('Paused', 'idle');
  }

  // --- Automation Loop ---
  async function runLoop() {
    let lastSentMessage = '';

    while (isRunning && queue.length > 0) {
      setLog('Checking Aristotle readiness...', 'waiting');

      // 1. Wait until Aristotle is Idle
      while (isRunning) {
        const stopBtn = getStopButton();
        const textarea = getComposerTextarea();
        const isBusy = !!stopBtn;
        const isReady = textarea && !textarea.disabled && !isBusy;

        if (isReady) break;

        setLog('Aristotle working... auto-scrolling', 'waiting');
        scrollFeedToBottom();
        await sleep(scrollIntervalSeconds * 1000);
      }

      if (!isRunning || queue.length === 0) break;

      // 2. Prepare next message
      const nextMessage = queue[0];
      const textarea = getComposerTextarea();

      if (!textarea) {
        setLog('Composer missing, retrying in 2s...', 'waiting');
        await sleep(2000);
        continue;
      }

      setLog(`Typing Markdown task (waiting 1s)...`, 'active');
      textarea.focus();
      setNativeValue(textarea, nextMessage);

      // Wait 1 second before submitting
      await sleep(1000);

      // 3. Submit
      setLog(`Submitting task...`, 'active');
      triggerSubmit(textarea);

      // Save for potential retry and pop from queue
      lastSentMessage = nextMessage;
      queue.shift();
      saveState();
      renderQueue();

      // 4. Wait for Aristotle to register the job
      setLog('Waiting for task to register...', 'waiting');
      let confirmationAttempts = 0;
      let didStart = false;
      while (isRunning && confirmationAttempts < 20) {
        await sleep(500);
        if (getStopButton()) {
          didStart = true;
          break;
        }
        confirmationAttempts++;
      }

      // 5. While task is active: scroll down every N seconds and wait for finish
      if (didStart) {
        setLog('Task running. Auto-scrolling down...', 'waiting');
        while (isRunning) {
          await sleep(scrollIntervalSeconds * 1000);
          scrollFeedToBottom();

          if (!getStopButton()) {
            break;
          }
        }
      }

      // 6. Task stopped: scroll down, wait 1.5s, check status
      setLog('Task stopped. Checking outcome...', 'waiting');
      scrollFeedToBottom();
      await sleep(1500);
      scrollFeedToBottom();

      const status = getLastExecutionStatus();
      console.log('[Aristotle Auto-Queue] Detected status banner:', status);

      // 7. Check if OUT OF BUDGET was encountered
      if (status.includes('OUT OF BUDGET') || (!status.includes('COMPLETED') && status.includes('BUDGET'))) {
        setLog('Out of Budget detected! Re-queueing continuation...', 'waiting');
        const continuationMsg = `continue previous task:\n${lastSentMessage}`;

        // Push back to the head of the queue so it retries immediately
        queue.unshift(continuationMsg);
        saveState();
        renderQueue();

        await sleep(2000);
        continue;
      }

      setLog(`Task finished with status: ${status}`, 'active');
      await sleep(2000);
    }

    if (queue.length === 0 && isRunning) {
      setLog('All tasks in queue completed!', 'active');
      stopRunner();
    }
  }

  // Initialize
  loadState(() => {
    scrollIntervalInput.value = scrollIntervalSeconds;
    renderQueue();
  });
})();
