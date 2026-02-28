document.addEventListener('DOMContentLoaded', () => {
  const formatSelect = document.getElementById('formatSelect');
  const numCountSelect = document.getElementById('numCountSelect');
  const levelSelect = document.getElementById('levelSelect');
  const questionCountSelect = document.getElementById('questionCountSelect');
  const startBtn = document.getElementById('startBtn');
  const checkAllBtn = document.getElementById('checkAllBtn');

  const questionsContainer = document.getElementById('questionsContainer');
  const overallFeedback = document.getElementById('overallFeedback');
  const scoreDisplay = document.getElementById('scoreDisplay');
  const scoreStats = document.getElementById('scoreStats');
  const initialPrompt = document.getElementById('initialPrompt');
  const buttonGroup = document.getElementById('buttonGroup');
  const quizCard = document.getElementById('quizCard');

  let questions = [];
  let answered = [];
  let results = [];
  let score = 0;
  let currentBits = 0;
  let timerStart = null;
  let timerInterval = null;
  let timerSeconds = 0;

  // Odoo integration
  const odooContext = window.__odoo_context__ || {};
  const urlParams = new URLSearchParams(window.location.search);
  const fallbackActiveId = parseInt(urlParams.get('active_id') || urlParams.get('res_id') || '', 10);
  const fallbackActiveModel = urlParams.get('active_model') || urlParams.get('res_model');
  const fallbackSubmissionState = urlParams.get('submission_state');

  const submissionId = odooContext.active_id || (Number.isFinite(fallbackActiveId) ? fallbackActiveId : null);
  const submissionModel = odooContext.active_model || fallbackActiveModel;
  let submissionState = odooContext.submission_state || fallbackSubmissionState;
  const isOdooContext = !!(submissionId && submissionModel === 'aps.resource.submission');

  function getQuestionCount() {
    return parseInt(questionCountSelect.value, 10);
  }

  // Parse URL parameters and set form values
  function loadSettingsFromURL() {
    const params = new URLSearchParams(window.location.search);
    const format = params.get('format');
    const level = params.get('level');
    const numCount = params.get('numCount');
    const questionCount = params.get('questionCount');

    let allParamsProvided = false;

    if (format && (format === 'binary' || format === 'hexadecimal')) {
      formatSelect.value = format;
      allParamsProvided = true;
    } else {
      allParamsProvided = false;
    }

    if (level && (level === 'easy' || level === 'medium' || level === 'hard')) {
      levelSelect.value = level;
    } else {
      allParamsProvided = false;
    }

    if (numCount && (numCount === '2' || numCount === '3' || numCount === '4')) {
      numCountSelect.value = numCount;
    } else {
      allParamsProvided = false;
    }

    if (questionCount) {
      const qCount = parseInt(questionCount, 10);
      if (qCount > 0) {
        questionCountSelect.value = qCount;
      } else {
        allParamsProvided = false;
      }
    } else {
      allParamsProvided = false;
    }

    return allParamsProvided && format && level && numCount && questionCount;
  }

  function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function startTimer() {
    stopTimer();
    timerStart = Date.now();
    timerSeconds = 0;
    timerInterval = setInterval(() => {
      timerSeconds = Math.floor((Date.now() - timerStart) / 1000);
      const timerDisplay = document.getElementById('timerDisplay');
      if (timerDisplay) {
        timerDisplay.textContent = formatTime(timerSeconds);
      }
    }, 1000);
  }

  function stopTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }

  function bitsForLevel(level) {
    if (level === 'easy') return 4;
    if (level === 'medium') return 8;
    return 12;
  }

  function randInt(maxInclusive) {
    return Math.floor(Math.random() * maxInclusive) + 1;
  }

  function generateRound() {
    const count = parseInt(numCountSelect.value, 10);
    const level = levelSelect.value;
    const bits = bitsForLevel(level);
    currentBits = bits;
    const max = (1 << bits) - 1;

    const out = [];
    for (let i = 0; i < getQuestionCount(); i++) {
      const nums = [];
      for (let j = 0; j < count; j++) nums.push(randInt(max));
      out.push(nums);
    }
    return out;
  }

  function formatNumber(n, fmt) {
    if (fmt === 'binary') return n.toString(2).padStart(currentBits, '0');
    if (fmt === 'hexadecimal') return n.toString(16).toUpperCase();
    return n.toString(10);
  }

  function formatQuestion(nums, fmt) {
    return nums.map(n => formatNumber(n, fmt)).join(' + ');
  }

  function hexsum(nums) {
    const sum = nums.reduce((a, b) => a + b, 0);
    return sum.toString(16).toUpperCase();
  }

  function correctForFormat(nums, fmt) {
    if (fmt === 'hexadecimal') {
      const s = hexsum(nums);
      return { asNumber: parseInt(s, 16), asString: s };
    }
    const sum = nums.reduce((a, b) => a + b, 0);
    const binaryStr = sum.toString(2);
    if (fmt === 'binary') {
      const padWidth = Math.max(currentBits, binaryStr.length);
      return { asNumber: sum, asString: binaryStr.padStart(padWidth, '0') };
    }
    return { asNumber: sum, asString: sum.toString(10) };
  }

  function updateScoreDisplay() {
    scoreDisplay.textContent = `Score: ${score} / ${getQuestionCount()}`;
  }

  function updateFormatBadge() {
    const badge = document.getElementById('formatBadge');
    const fmt = formatSelect.value;
    if (fmt === 'binary') {
      badge.textContent = 'B';
      badge.className = 'badge bg-info text-dark';
    } else if (fmt === 'hexadecimal') {
      badge.textContent = 'H';
      badge.className = 'badge bg-success text-dark';
    }
  }

  function makeAnswersReadonly() {
    const inputs = questionsContainer.querySelectorAll('.answer-input');
    inputs.forEach(input => input.readOnly = true);
    checkAllBtn.textContent = 'Practice Again';
  }

  function makeAnswersEditable() {
    const inputs = questionsContainer.querySelectorAll('.answer-input');
    inputs.forEach(input => input.readOnly = false);
    checkAllBtn.textContent = 'Check All';
  }

  function renderQuestions() {
    questionsContainer.innerHTML = '';
    overallFeedback.innerHTML = '';
    const qCount = getQuestionCount();
    answered = new Array(qCount).fill(false);
    results = new Array(qCount).fill(false);
    score = 0;
    updateScoreDisplay();
    initialPrompt.style.display = 'none';
    scoreStats.style.display = 'block';
    buttonGroup.style.display = 'flex';
    quizCard.style.display = 'block';

    const fmt = formatSelect.value;

    for (let i = 0; i < qCount; i++) {
      const nums = questions[i];
      const qText = formatQuestion(nums, fmt) + ' = ?';

      const item = document.createElement('div');
      item.className = 'list-group-item';
      item.innerHTML = `
        <div class="d-flex align-items-start">
          <div class="me-3">
            <span class="badge ${fmt === 'binary' ? 'bg-info text-dark' : 'bg-success text-dark'}">${fmt === 'binary' ? 'B' : 'H'}</span>
          </div>
          <div class="flex-fill">
            <div class="fw-bold question-text">${qText}</div>
            <div class="mt-2 input-group">
              <input data-index="${i}" class="form-control answer-input" placeholder="${fmt === 'binary' ? 'Answer in Binary' : 'Answer in Hexadecimal'}">
              <button data-index="${i}" class="btn btn-outline-primary check-btn" type="button">Check</button>
            </div>
            <div class="mt-2 feedback"></div>
          </div>
        </div>
      `;

      questionsContainer.appendChild(item);
    }

    startTimer();
    // debugger;
  }

  function checkQuestion(index) {
    const item = questionsContainer.children[index];
    if (!item) return;
    const input = item.querySelector('.answer-input');
    const fb = item.querySelector('.feedback');
    const user = input.value.trim();
    const fmt = formatSelect.value;
    if (user === '') {
      fb.innerHTML = '<div class="text-warning">Please enter an answer.</div>';
      return;
    }

    let userVal;
    if (fmt === 'binary') {
      if (!/^[01]+$/.test(user.replace(/\s+/g, ''))) {
        fb.innerHTML = '<div class="text-danger">Invalid binary format.</div>';
        return;
      }
      userVal = parseInt(user.replace(/\s+/g, ''), 2);
    } else if (fmt === 'hexadecimal') {
      if (!/^[0-9a-fA-F]+$/.test(user.replace(/\s+/g, ''))) {
        fb.innerHTML = '<div class="text-danger">Invalid hexadecimal format.</div>';
        return;
      }
      userVal = parseInt(user.replace(/\s+/g, ''), 16);
    } else {
      if (!/^\d+$/.test(user.replace(/\s+/g, ''))) {
        fb.innerHTML = '<div class="text-danger">Invalid number format.</div>';
        return;
      }
      userVal = parseInt(user.replace(/\s+/g, ''), 10);
    }

    const nums = questions[index];
    const corr = correctForFormat(nums, fmt);
    if (userVal === corr.asNumber) {
      fb.innerHTML = '<div class="text-success">Correct</div>';
      if (!answered[index]) {
        score += 1;
        updateScoreDisplay();
      }
      results[index] = true;
    } else {
      fb.innerHTML = `<div class="text-danger">Wrong. Correct: <strong>${corr.asString}</strong></div>`;
      results[index] = false;
    }
    answered[index] = true;
    input.disabled = true;
    const checkBtn = item.querySelector('.check-btn');
    if (checkBtn) checkBtn.disabled = true;
  }

  function buildResultsHtml() {
    const fmt = formatSelect.value;
    const rows = questions.map((q, i) => {
      const nums = q;
      const qText = formatQuestion(nums, fmt) + ' = ?';
      const corr = correctForFormat(nums, fmt);
      const userAnswer = questionsContainer.children[i]?.querySelector('.answer-input')?.value || '(Empty)';
      const isCorrect = results[i];
      const bgColor = isCorrect ? "#d4edda" : "#f8d7da";
      const textColor = isCorrect ? "#155724" : "#721c24";

      return `
        <tr>
          <td style="padding: 8px; border: 1px solid #dee2e6;">${qText}</td>
          <td style="padding: 8px; border: 1px solid #dee2e6; background-color: ${bgColor}; color: ${textColor}; font-weight: bold;">
            ${userAnswer}
          </td>
          <td style="padding: 8px; border: 1px solid #dee2e6;">${corr.asString}</td>
        </tr>`;
    }).join("");

    const timeDisplay = formatTime(timerSeconds);
    return `
      <div style="font-family: sans-serif; margin-bottom: 8px;">
        <strong>Time taken:</strong> ${timeDisplay}
      </div>
      <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-family: sans-serif;">
        <thead>
          <tr style="background-color: #f8f9fa;">
            <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Question</th>
            <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Your Answer</th>
            <th style="padding: 8px; border: 1px solid #dee2e6; text-align: left; font-weight:bold">Correct Answer</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  async function submitToOdoo() {
    if (!isOdooContext) {
      console.log('Not in Odoo submission context, skipping submission');
      return;
    }

    if (submissionState !== 'assigned') {
      console.warn('This task has already been submitted so these results can not be saved.');
      return 'already-submitted';
    }

    const htmlReport = buildResultsHtml();
    const hours = Math.round((timerSeconds / 3600) * 10) / 10;

    try {
      // Validate submission can still be written before attempting to save
      if (submissionState !== 'assigned') {
        console.warn('Cannot save: This task has already been submitted.');
        return false;
      }

      if (!submissionId) {
        console.error('Cannot save: No submission ID found.');
        return false;
      }

      // debugger;
      const values = {
        score: score,
        out_of_marks: getQuestionCount() ,
        answer: htmlReport,
        actual_duration: hours,
        state: 'submitted'
      };

      const payload = {
        jsonrpc: '2.0',
        method: 'call',
        params: {
          model: 'aps.resource.submission',
          method: 'write',
          args: [[submissionId], values],
          kwargs: {
            context: odooContext.context || {}
          }
        },
        id: Date.now()
      };

      const response = await fetch('/web/dataset/call_kw/aps.resource.submission/write', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRF-Token': document.querySelector('[name="csrf_token"]')?.content || ''
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        console.error('Error saving submission: HTTP', response.status, response.statusText);
        console.warn('Error saving submission.');
        return false;
      }

      const data = await response.json();

      if (data.error) {
        console.error('Error saving submission:', data.error);
        console.warn('Error saving submission.');
        return false;
      }

      console.log('Official submission saved!');
      // Update local state to prevent re-submission
      submissionState = 'submitted';
      return true;
    } catch (error) {
      console.error('Error saving submission:', error);
      console.warn('Error saving submission.');
      return false;
    }
  }

  questionsContainer.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const idx = parseInt(btn.dataset.index, 10);
    if (btn.classList.contains('check-btn')) checkQuestion(idx);
  });

  checkAllBtn.addEventListener('click', async () => {
    // If button says "Practice Again", generate a new round instead of checking answers
    if (checkAllBtn.textContent === 'Practice Again') {
      questions = generateRound();
      updateFormatBadge();
      renderQuestions();
      makeAnswersEditable();
      return;
    }
    
    for (let i = 0; i < getQuestionCount(); i++) {
      const item = questionsContainer.children[i];
      if (!item) continue;
      const input = item.querySelector('.answer-input');
      if (!answered[i]) {
        checkQuestion(i);
      }
    }
    stopTimer();
    
    const feedbackDiv = overallFeedback;
    
    // If in Odoo context, automatically submit results
    if (isOdooContext) {
      const success = await submitToOdoo();
      
      if (success === 'already-submitted') {
        // Already submitted - show info that this is practice/review
        showOdooLikeToast('info', 'Review Mode', `<strong>Review Mode:</strong> This submission has already been saved. You are reviewing your results. Score: ${score} / ${getQuestionCount()}`);
      } else if (success) {
        showOdooLikeToast('success', 'Saved!', `<strong>Success!</strong> Your results have been saved to APEX. Score: ${score} / ${getQuestionCount()}`);
      } else {
        showOdooLikeToast('danger', 'Error', `<strong>Error:</strong> Failed to save results. Score: ${score} / ${getQuestionCount()}`);
      }
    } else {
      // Practice mode - show blue info message
      showOdooLikeToast('info', 'Practice Mode', `<strong>Practice Mode:</strong> Your score: ${score} / ${getQuestionCount()}`);
    }
    
    // Make answers readonly and change button to "Practice Again"
    makeAnswersReadonly();
  });

  startBtn.addEventListener('click', () => {
    questions = generateRound();
    updateFormatBadge();
    renderQuestions();
    
    // Reset answers to editable and button back to "Check All"
    makeAnswersEditable();

    // Display URL params at bottom of page
    const params = new URLSearchParams({
      format: formatSelect.value,
      level: levelSelect.value,
      numCount: numCountSelect.value,
      questionCount: questionCountSelect.value,
    });
    const paramsDisplay = document.getElementById('paramsDisplay');
    if (paramsDisplay) {
      paramsDisplay.textContent = `URL: ?${params.toString()}`;
    }
  });

  function updateInitialPrompt() {
    const qCount = getQuestionCount();
    initialPrompt.textContent = `Press Start to generate ${qCount} question${qCount !== 1 ? 's' : ''}.`;
  }

  formatSelect.addEventListener('change', () => {
    updateFormatBadge();
    if (questions.length) renderQuestions();
  });

  questionCountSelect.addEventListener('change', () => {
    updateInitialPrompt();
  });

  updateFormatBadge();
  updateInitialPrompt();

  // Load settings from URL and auto-start if all parameters provided
  if (loadSettingsFromURL()) {
    updateFormatBadge();
    updateInitialPrompt();
    setTimeout(() => {
      startBtn.click();
    }, 100);
  }
});


