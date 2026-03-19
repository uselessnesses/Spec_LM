/**
 * app.js — Build Your Own LLM
 * Main application logic: state management, view transitions, Ollama streaming.
 */

/* =========================================================
   STATE
   ========================================================= */
let currentFunder   = null;   // funder object
let currentStageIdx = 0;      // 0-based index into STAGES
let selections      = [];     // array of { stageId, stageName, optionId, label, description, ethics }
let currentOptIdx   = 0;      // current dial position index
let dial            = null;   // RotaryDial instance

/* =========================================================
   DOM REFS (resolved after DOMContentLoaded)
   ========================================================= */
let views, funderView, stageView, resultsView;
let funderIcon, funderTypeBadge, funderName, funderTagline, funderBrief;
let headerStageText, stageQuestion;
let dialWrapper, previewInner, previewOptionLetter, previewOptionName;
let previewDesc, previewEthicsText;
let selectBtn;
let footerFunderIcon, footerFunderName;
let progressDots;
let summaryText, summaryCursor, summaryLoading;
let specsSidebarItems, specsFunderName, specsFunderType;
let transitionFlash;

/* =========================================================
   INIT
   ========================================================= */
document.addEventListener('DOMContentLoaded', () => {
  // Resolve DOM refs
  views         = document.querySelectorAll('.view');
  funderView    = document.getElementById('funder-view');
  stageView     = document.getElementById('stage-view');
  resultsView   = document.getElementById('results-view');

  funderIcon      = document.getElementById('funder-icon');
  funderTypeBadge = document.getElementById('funder-type-badge');
  funderName      = document.getElementById('funder-name');
  funderTagline   = document.getElementById('funder-tagline');
  funderBrief     = document.getElementById('funder-brief');

  headerStageText = document.getElementById('header-stage-text');
  stageQuestion   = document.getElementById('stage-question');
  dialWrapper     = document.getElementById('dial-wrapper');
  previewInner    = document.getElementById('preview-inner');
  previewOptionLetter = document.getElementById('preview-option-letter');
  previewOptionName   = document.getElementById('preview-option-name');
  previewDesc         = document.getElementById('preview-description');
  previewEthicsText   = document.getElementById('preview-ethics-text');
  selectBtn           = document.getElementById('select-btn');

  footerFunderIcon = document.getElementById('footer-funder-icon');
  footerFunderName = document.getElementById('footer-funder-name');
  progressDots     = document.getElementById('progress-dots');

  summaryText     = document.getElementById('summary-text');
  summaryCursor   = document.getElementById('summary-cursor');
  summaryLoading  = document.getElementById('summary-loading');
  specsSidebarItems = document.getElementById('specs-sidebar-items');
  specsFunderName   = document.getElementById('specs-funder-name');
  specsFunderType   = document.getElementById('specs-funder-type');
  transitionFlash   = document.getElementById('transition-flash');

  // Build progress dots
  buildProgressDots();

  // Button events
  document.getElementById('accept-btn').addEventListener('click', acceptMission);
  document.getElementById('reroll-btn').addEventListener('click', rerollFunder);
  selectBtn.addEventListener('click', onSelect);
  document.getElementById('generate-skip-btn').addEventListener('click', skipToGenerate);
  document.getElementById('start-over-btn').addEventListener('click', resetApp);
  document.getElementById('start-over-results-btn').addEventListener('click', resetApp);

  // Kick off
  initApp();
});

/* =========================================================
   BUILD PROGRESS DOTS
   ========================================================= */
function buildProgressDots() {
  progressDots.innerHTML = '';
  STAGES.forEach((_, i) => {
    const dot = document.createElement('div');
    dot.className = 'progress-dot';
    dot.id = `dot-${i}`;
    dot.title = STAGES[i].name;
    progressDots.appendChild(dot);
  });
}

function updateProgressDots() {
  STAGES.forEach((_, i) => {
    const dot = document.getElementById(`dot-${i}`);
    if (!dot) return;
    dot.classList.remove('complete', 'current');
    if (i < currentStageIdx) dot.classList.add('complete');
    else if (i === currentStageIdx) dot.classList.add('current');
  });
}

/* =========================================================
   FUNDER SCREEN
   ========================================================= */
function initApp() {
  currentFunder   = randomFunder();
  currentStageIdx = 0;
  selections      = [];
  currentOptIdx   = 0;

  renderFunderCard();
  showView('funder');
}

function randomFunder(exclude) {
  let pool = FUNDERS;
  if (exclude) pool = FUNDERS.filter(f => f.id !== exclude.id);
  if (pool.length === 0) pool = FUNDERS;
  return pool[Math.floor(Math.random() * pool.length)];
}

function rerollFunder() {
  const prev = currentFunder;
  currentFunder = randomFunder(prev);
  renderFunderCard(true);
}

function renderFunderCard(animate) {
  const f = currentFunder;

  if (animate) {
    funderIcon.style.transform = 'scale(0.8)';
    funderIcon.style.opacity = '0';
    setTimeout(() => {
      funderIcon.style.transition = 'all 0.3s ease';
      funderIcon.style.transform = 'scale(1)';
      funderIcon.style.opacity = '1';
    }, 50);
  }

  funderIcon.textContent   = f.icon;
  funderTypeBadge.textContent = f.type === 'evil' ? 'CORPORATE / EVIL'
                              : f.type === 'neutral' ? 'NEUTRAL / AMBIGUOUS'
                              : 'POSITIVE / PROGRESSIVE';
  funderTypeBadge.className = `funder-type-badge ${f.type}`;
  funderName.textContent    = f.name;
  funderTagline.textContent = `"${f.tagline}"`;
  funderBrief.textContent   = f.brief;
}

function acceptMission() {
  showView('stage');
  setTimeout(() => {
    initStage(0);
  }, 100);
}

/* =========================================================
   STAGE SCREEN
   ========================================================= */
function initStage(index) {
  currentStageIdx = index;
  currentOptIdx   = 0;
  const stage = STAGES[index];

  // Header
  headerStageText.innerHTML = `STAGE <span>${index + 1} OF ${STAGES.length}</span>: <span>${stage.name.toUpperCase()}</span>`;

  // Question
  stageQuestion.textContent = stage.question;

  // Footer funder badge
  footerFunderIcon.textContent = currentFunder.icon;
  footerFunderName.textContent  = currentFunder.name;

  // Progress dots
  updateProgressDots();

  // Build or reinit dial
  const optionIds    = stage.options.map(o => o.id);
  const optionLabels = stage.options.map((_, i) => ['A','B','C','D'][i]);

  if (!dial) {
    dial = new RotaryDial({
      container:    dialWrapper,
      optionIds,
      optionLabels,
      onChange:     onDialChange,
      size:         280,
    });
  } else {
    dial.reinit({ optionIds, optionLabels });
  }

  // Reset preview to option 0
  onDialChange(0);

  // Enable select button
  selectBtn.disabled = false;
  selectBtn.classList.remove('locked', 'flash');
}

function onDialChange(index) {
  currentOptIdx = index;
  const stage  = STAGES[currentStageIdx];
  const option = stage.options[index];
  if (!option) return;

  const letters = ['A', 'B', 'C', 'D'];

  // Fade out, update, fade in
  previewInner.classList.add('fading');
  setTimeout(() => {
    previewOptionLetter.textContent = letters[index] || String.fromCharCode(65 + index);
    previewOptionName.textContent   = option.label;
    previewDesc.textContent         = option.description;
    previewEthicsText.textContent   = option.ethics;
    previewInner.classList.remove('fading');
  }, 200);
}

function onSelect() {
  const stage  = STAGES[currentStageIdx];
  const option = stage.options[currentOptIdx];
  const letters = ['A', 'B', 'C', 'D'];

  // Record selection
  selections[currentStageIdx] = {
    stageId:     stage.id,
    stageName:   stage.name,
    optionId:    option.id,
    optionIndex: currentOptIdx,
    label:       `${letters[currentOptIdx]}: ${option.label}`,
    description: option.description,
    ethics:      option.ethics,
  };

  // Flash animation
  selectBtn.classList.remove('flash');
  void selectBtn.offsetWidth; // reflow to restart animation
  selectBtn.classList.add('flash');
  selectBtn.disabled = true;
  selectBtn.classList.add('locked');

  // Flash overlay
  triggerFlash();

  // Advance after brief pause
  setTimeout(() => {
    const next = currentStageIdx + 1;
    if (next >= STAGES.length) {
      generateSummary();
    } else {
      initStage(next);
      selectBtn.disabled = false;
      selectBtn.classList.remove('locked', 'flash');
    }
  }, 500);
}

function skipToGenerate() {
  // Fill any unselected stages with option 0 defaults
  const letters = ['A', 'B', 'C', 'D'];
  STAGES.forEach((stage, i) => {
    if (!selections[i]) {
      const option = stage.options[0];
      selections[i] = {
        stageId:     stage.id,
        stageName:   stage.name,
        optionId:    option.id,
        optionIndex: 0,
        label:       `A: ${option.label}`,
        description: option.description,
        ethics:      option.ethics,
      };
    }
  });
  generateSummary();
}

/* =========================================================
   TRANSITION HELPERS
   ========================================================= */
function triggerFlash() {
  transitionFlash.classList.add('active');
  setTimeout(() => transitionFlash.classList.remove('active'), 150);
}

function showView(name) {
  const map = { funder: funderView, stage: stageView, results: resultsView };
  views.forEach(v => v.classList.remove('active'));
  const target = map[name];
  if (target) {
    requestAnimationFrame(() => target.classList.add('active'));
  }
}

/* =========================================================
   RESULTS SCREEN & OLLAMA STREAMING
   ========================================================= */
async function generateSummary() {
  // Build specs sidebar
  buildSpecsSidebar();

  // Show results view
  showView('results');
  summaryText.textContent = '';
  summaryCursor.classList.remove('done');
  summaryLoading.style.display = 'flex';

  const payload = {
    funder:     currentFunder,
    selections: selections.map(s => ({
      stageName:   s.stageName,
      label:       s.label,
      description: s.description,
    })),
  };

  try {
    const response = await fetch('/api/generate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    if (!response.ok) {
      summaryLoading.style.display = 'none';
      showError(`Server error: ${response.status} ${response.statusText}`);
      return;
    }

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    summaryLoading.style.display = 'none';

    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      buffer += chunk;

      // Check for error message
      if (buffer.startsWith('\n\n[')) {
        summaryText.textContent = '';
        showError(buffer.trim());
        summaryCursor.classList.add('done');
        return;
      }

      summaryText.textContent = buffer;
    }

    summaryCursor.classList.add('done');

  } catch (err) {
    summaryLoading.style.display = 'none';
    showError(`Network error: ${err.message}`);
  }
}

function showError(msg) {
  const div = document.createElement('div');
  div.className = 'summary-error';
  div.textContent = msg;
  summaryText.parentNode.insertBefore(div, summaryText.nextSibling);
}

function buildSpecsSidebar() {
  // Funder
  specsFunderName.textContent  = `${currentFunder.icon}  ${currentFunder.name}`;
  specsFunderType.textContent  = currentFunder.type.toUpperCase();
  specsFunderType.className    = `specs-funder-type ${currentFunder.type}`;

  // Stage selections
  specsSidebarItems.innerHTML = '';
  selections.forEach((sel, i) => {
    const item = document.createElement('div');
    item.className = 'spec-item';
    item.innerHTML = `
      <div class="spec-stage">${sel.stageName}</div>
      <div class="spec-choice">${sel.label}</div>
    `;
    specsSidebarItems.appendChild(item);
  });
}

/* =========================================================
   RESET
   ========================================================= */
function resetApp() {
  // Clear any lingering error elements
  document.querySelectorAll('.summary-error').forEach(el => el.remove());
  summaryCursor.classList.remove('done');
  summaryText.textContent = '';
  summaryLoading.style.display = 'none';

  // Reset dial (will be reinit'd on next stage entry)
  if (dial) {
    dial = null;
    dialWrapper.innerHTML = '';
  }

  initApp();
}
