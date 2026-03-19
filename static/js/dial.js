/**
 * dial.js — Rotary Dial Component
 * Renders an SVG-based rotary knob with snap-to-position behaviour.
 * Options are placed around the circumference; the knob can be dragged or
 * option labels can be clicked directly.
 */

class RotaryDial {
  /**
   * @param {Object} config
   * @param {HTMLElement} config.container   — .dial-wrapper element
   * @param {string[]}    config.optionIds   — option ids in order
   * @param {string[]}    config.optionLabels — short labels (A/B/C/D)
   * @param {Function}    config.onChange    — called with (index) on change
   * @param {number}      [config.size=280]  — SVG diameter in px
   */
  constructor({ container, optionIds, optionLabels, onChange, size = 280 }) {
    this.container    = container;
    this.optionIds    = optionIds;
    this.optionLabels = optionLabels;
    this.onChange     = onChange;
    this.size         = size;
    this.n            = optionIds.length;

    // Angle state (radians). 0 = top (12 o'clock).
    this.currentAngle = 0;          // displayed/animated angle
    this.targetAngle  = 0;          // snapped target angle
    this.currentIndex = 0;

    // Drag state
    this.isDragging   = false;
    this.dragStartAngle = 0;
    this.dragStartMouseAngle = 0;

    // rAF
    this._rafId = null;
    this._animate = this._animate.bind(this);

    this._build();
    this._bindEvents();
    this._snapTo(0, false); // start at option 0
  }

  /* -------------------------------------------------------
     Build
  ------------------------------------------------------- */
  _build() {
    const s = this.size;
    const cx = s / 2;
    const cy = s / 2;
    const R = s / 2 - 4; // outer radius of bezel
    const knobR = R * 0.52; // inner knob radius

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', s);
    svg.setAttribute('height', s);
    svg.setAttribute('viewBox', `0 0 ${s} ${s}`);
    svg.id = 'dial-svg';

    // Defs: radial gradient for knob
    const defs = document.createElementNS(svgNS, 'defs');

    const grad = document.createElementNS(svgNS, 'radialGradient');
    grad.id = 'knob-grad';
    grad.setAttribute('cx', '40%');
    grad.setAttribute('cy', '35%');
    [
      ['0%', '#2a2a2a'],
      ['60%', '#151515'],
      ['100%', '#0a0a0a'],
    ].forEach(([offset, color]) => {
      const stop = document.createElementNS(svgNS, 'stop');
      stop.setAttribute('offset', offset);
      stop.setAttribute('stop-color', color);
      grad.appendChild(stop);
    });
    defs.appendChild(grad);

    // Bezel gradient
    const bezelGrad = document.createElementNS(svgNS, 'radialGradient');
    bezelGrad.id = 'bezel-grad';
    bezelGrad.setAttribute('cx', '50%');
    bezelGrad.setAttribute('cy', '50%');
    [
      ['0%', '#1e1e1e'],
      ['100%', '#0d0d0d'],
    ].forEach(([offset, color]) => {
      const stop = document.createElementNS(svgNS, 'stop');
      stop.setAttribute('offset', offset);
      stop.setAttribute('stop-color', color);
      bezelGrad.appendChild(stop);
    });
    defs.appendChild(bezelGrad);

    svg.appendChild(defs);

    // Outer bezel ring (tick marks)
    const bezel = document.createElementNS(svgNS, 'circle');
    bezel.setAttribute('cx', cx);
    bezel.setAttribute('cy', cy);
    bezel.setAttribute('r', R);
    bezel.setAttribute('fill', 'url(#bezel-grad)');
    bezel.setAttribute('stroke', '#222');
    bezel.setAttribute('stroke-width', '1.5');
    svg.appendChild(bezel);

    // Tick marks at option positions
    for (let i = 0; i < this.n; i++) {
      const angle = this._optionAngle(i);
      const tickOuter = R - 6;
      const tickInner = R - 16;
      const x1 = cx + Math.sin(angle) * tickOuter;
      const y1 = cy - Math.cos(angle) * tickOuter;
      const x2 = cx + Math.sin(angle) * tickInner;
      const y2 = cy - Math.cos(angle) * tickInner;
      const tick = document.createElementNS(svgNS, 'line');
      tick.setAttribute('x1', x1); tick.setAttribute('y1', y1);
      tick.setAttribute('x2', x2); tick.setAttribute('y2', y2);
      tick.setAttribute('stroke', '#333');
      tick.setAttribute('stroke-width', '2');
      tick.setAttribute('stroke-linecap', 'round');
      svg.appendChild(tick);
    }

    // Knob body (rotates)
    const knobGroup = document.createElementNS(svgNS, 'g');
    knobGroup.id = 'dial-knob-group';

    const knob = document.createElementNS(svgNS, 'circle');
    knob.setAttribute('cx', cx);
    knob.setAttribute('cy', cy);
    knob.setAttribute('r', knobR);
    knob.setAttribute('fill', 'url(#knob-grad)');
    knob.setAttribute('stroke', '#333');
    knob.setAttribute('stroke-width', '1');
    knobGroup.appendChild(knob);

    // Indicator line from center toward top
    const indLen = knobR * 0.75;
    const ind = document.createElementNS(svgNS, 'line');
    ind.id = 'dial-indicator';
    ind.setAttribute('x1', cx);
    ind.setAttribute('y1', cy);
    ind.setAttribute('x2', cx);
    ind.setAttribute('y2', cy - indLen);
    ind.setAttribute('stroke', '#00ff88');
    ind.setAttribute('stroke-width', '3');
    ind.setAttribute('stroke-linecap', 'round');
    knobGroup.appendChild(ind);

    // Inner highlight dot
    const dot = document.createElementNS(svgNS, 'circle');
    dot.setAttribute('cx', cx);
    dot.setAttribute('cy', cy - indLen * 0.85);
    dot.setAttribute('r', '4');
    dot.setAttribute('fill', '#00ff88');
    dot.setAttribute('filter', 'url(#glow)');
    knobGroup.appendChild(dot);

    // Glow filter
    const filter = document.createElementNS(svgNS, 'filter');
    filter.id = 'glow';
    filter.setAttribute('x', '-50%');
    filter.setAttribute('y', '-50%');
    filter.setAttribute('width', '200%');
    filter.setAttribute('height', '200%');
    const feGaussian = document.createElementNS(svgNS, 'feGaussianBlur');
    feGaussian.setAttribute('stdDeviation', '3');
    feGaussian.setAttribute('result', 'blur');
    filter.appendChild(feGaussian);
    const feMerge = document.createElementNS(svgNS, 'feMerge');
    [document.createElementNS(svgNS, 'feMergeNode'), document.createElementNS(svgNS, 'feMergeNode')].forEach((n, i) => {
      if (i === 0) n.setAttribute('in', 'blur');
      else n.setAttribute('in', 'SourceGraphic');
      feMerge.appendChild(n);
    });
    filter.appendChild(feMerge);
    defs.appendChild(filter);

    svg.appendChild(knobGroup);

    // Centre cap
    const cap = document.createElementNS(svgNS, 'circle');
    cap.setAttribute('cx', cx);
    cap.setAttribute('cy', cy);
    cap.setAttribute('r', '14');
    cap.setAttribute('fill', '#0d0d0d');
    cap.setAttribute('stroke', '#333');
    cap.setAttribute('stroke-width', '1');
    svg.appendChild(cap);

    this.svg = svg;
    this.knobGroup = knobGroup;
    this.cx = cx;
    this.cy = cy;
    this.knobR = knobR;
    this.R = R;

    this.container.appendChild(svg);

    // Build option labels in DOM (outside SVG, positioned via CSS)
    this._buildLabels();
  }

  _buildLabels() {
    // Remove any existing labels
    this.container.querySelectorAll('.dial-label').forEach(el => el.remove());

    const labelR = this.R + 38; // distance from centre for labels
    const letters = ['A', 'B', 'C', 'D'];

    this.labelEls = this.optionIds.map((id, i) => {
      const angle = this._optionAngle(i);
      const x = this.cx + Math.sin(angle) * labelR;
      const y = this.cy - Math.cos(angle) * labelR;

      const el = document.createElement('div');
      el.className = 'dial-label';
      el.dataset.index = i;
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;

      const letter = document.createElement('span');
      letter.className = 'dial-option-letter';
      letter.textContent = letters[i] || String.fromCharCode(65 + i);

      el.appendChild(letter);
      el.addEventListener('click', () => this._snapTo(i, true));
      this.container.appendChild(el);
      return el;
    });
  }

  /* -------------------------------------------------------
     Events
  ------------------------------------------------------- */
  _bindEvents() {
    // Mouse drag on SVG
    this.svg.addEventListener('mousedown', (e) => this._onDragStart(e));
    window.addEventListener('mousemove', (e) => this._onDragMove(e));
    window.addEventListener('mouseup',   (e) => this._onDragEnd(e));

    // Touch
    this.svg.addEventListener('touchstart', (e) => this._onDragStart(e.touches[0]), { passive: true });
    window.addEventListener('touchmove', (e) => { if (this.isDragging) { e.preventDefault(); this._onDragMove(e.touches[0]); } }, { passive: false });
    window.addEventListener('touchend',  (e) => this._onDragEnd(e));
  }

  _getMouseAngle(e) {
    const rect = this.svg.getBoundingClientRect();
    const mx = e.clientX - rect.left - this.cx;
    const my = e.clientY - rect.top  - this.cy;
    return Math.atan2(mx, -my); // 0 at top
  }

  _onDragStart(e) {
    this.isDragging = true;
    this.dragStartAngle = this.currentAngle;
    this.dragStartMouseAngle = this._getMouseAngle(e);
  }

  _onDragMove(e) {
    if (!this.isDragging) return;
    const mouseAngle = this._getMouseAngle(e);
    let delta = mouseAngle - this.dragStartMouseAngle;
    // Normalise delta to [-π, π]
    while (delta >  Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;

    this.currentAngle = this.dragStartAngle + delta;
    this._applyRotation(this.currentAngle);

    // Update preview based on nearest option (no snap yet)
    const nearest = this._nearestIndex(this.currentAngle);
    if (nearest !== this.currentIndex) {
      this.currentIndex = nearest;
      this._updateLabels();
      this.onChange(nearest);
    }
  }

  _onDragEnd(_e) {
    if (!this.isDragging) return;
    this.isDragging = false;
    this._snapTo(this._nearestIndex(this.currentAngle), true);
  }

  /* -------------------------------------------------------
     Snap & Animate
  ------------------------------------------------------- */
  _optionAngle(index) {
    // Distribute options evenly around the circle, starting from top
    const startOffset = -Math.PI * 0.15; // slight offset so A isn't at dead top
    return startOffset + (2 * Math.PI / this.n) * index;
  }

  _nearestIndex(angle) {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < this.n; i++) {
      let diff = angle - this._optionAngle(i);
      // Normalise
      while (diff >  Math.PI) diff -= 2 * Math.PI;
      while (diff < -Math.PI) diff += 2 * Math.PI;
      const dist = Math.abs(diff);
      if (dist < bestDist) { bestDist = dist; best = i; }
    }
    return best;
  }

  _snapTo(index, animate) {
    this.currentIndex = index;
    this.targetAngle = this._optionAngle(index);
    if (!animate) {
      this.currentAngle = this.targetAngle;
      this._applyRotation(this.currentAngle);
    } else {
      this._startAnimation();
    }
    this._updateLabels();
    this.onChange(index);
  }

  _startAnimation() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = requestAnimationFrame(this._animate);
  }

  _animate() {
    const diff = this.targetAngle - this.currentAngle;
    // Normalise diff
    let d = diff;
    while (d >  Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;

    if (Math.abs(d) < 0.001) {
      this.currentAngle = this.targetAngle;
      this._applyRotation(this.currentAngle);
      this._rafId = null;
      return;
    }
    this.currentAngle += d * 0.18; // lerp factor — feel of the snap
    this._applyRotation(this.currentAngle);
    this._rafId = requestAnimationFrame(this._animate);
  }

  _applyRotation(angle) {
    const deg = (angle * 180) / Math.PI;
    this.knobGroup.setAttribute(
      'transform',
      `rotate(${deg}, ${this.cx}, ${this.cy})`
    );
  }

  _updateLabels() {
    if (!this.labelEls) return;
    this.labelEls.forEach((el, i) => {
      el.classList.toggle('active', i === this.currentIndex);
    });
  }

  /* -------------------------------------------------------
     Public API
  ------------------------------------------------------- */
  /** Reinitialise with new options (for stage change) */
  reinit({ optionIds, optionLabels }) {
    this.optionIds    = optionIds;
    this.optionLabels = optionLabels;
    this.n            = optionIds.length;
    if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }

    // Rebuild tick marks in SVG bezel
    this.svg.querySelectorAll('line[data-tick]').forEach(el => el.remove());
    const svgNS = 'http://www.w3.org/2000/svg';
    for (let i = 0; i < this.n; i++) {
      const angle = this._optionAngle(i);
      const tickOuter = this.R - 6;
      const tickInner = this.R - 16;
      const x1 = this.cx + Math.sin(angle) * tickOuter;
      const y1 = this.cy - Math.cos(angle) * tickOuter;
      const x2 = this.cx + Math.sin(angle) * tickInner;
      const y2 = this.cy - Math.cos(angle) * tickInner;
      const tick = document.createElementNS(svgNS, 'line');
      tick.setAttribute('x1', x1); tick.setAttribute('y1', y1);
      tick.setAttribute('x2', x2); tick.setAttribute('y2', y2);
      tick.setAttribute('stroke', '#333');
      tick.setAttribute('stroke-width', '2');
      tick.setAttribute('stroke-linecap', 'round');
      tick.dataset.tick = '1';
      this.svg.insertBefore(tick, this.knobGroup);
    }

    this._buildLabels();
    this._snapTo(0, false);
  }

  getCurrentIndex() { return this.currentIndex; }
}
