document.addEventListener('DOMContentLoaded', () => {
  // Minimal but complete recommendation UI script.
  const form = document.getElementById('recommendForm');
  const errEl = document.getElementById('recommendError');
  const resultWrapper = document.getElementById('recommendResultWrapper');
  const clearBtn = document.getElementById('clearRecommend');
  const submitBtn = document.getElementById('submitRecommend');
  const moodInput = document.getElementById('mood');
  const cardDeck = document.getElementById('cardDeck');

  // Simple runtime storage for swipes
  window._swipeResults = { likes: [], dislikes: [] };
  window._swipeLog = [];

  const esc = (s) => String(s || '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const escAttr = (s) => encodeURI(String(s || ''));

  function clearCardDeck() {
    cardDeck.innerHTML = '<div id="noRecs" class="text-muted">No recommendations yet — submit the form above.</div>';
    window._swipeResults = { likes: [], dislikes: [] };
    window._swipeLog = [];
    const summary = document.getElementById('swipeSummary');
    if (summary) summary.classList.add('d-none');
  }

  function renderCardDeck(items) {
    clearCardDeck();
    if (!Array.isArray(items) || items.length === 0) return;

    // render top item last so the first recommendation appears on top
    items.slice().reverse().forEach((it, idx) => {
      const card = document.createElement('div');
      card.className = 'swipe-card';
      card.style.zIndex = 100 + idx;
      card.dataset.payload = JSON.stringify(it || {});

      card.innerHTML = `
        <div>
          <div class="title">${esc(it.title)}</div>
          <div class="reason">${esc(it.reason)}</div>
          <div class="synopsis">${esc(it.synopsis)}</div>
        </div>
        <div>
          <div class="meta">${esc(it.showdate)} ${esc(it.showtime)} at ${esc(it.cinema)}</div>
          <div class="d-flex justify-content-end">
            ${it.ticket_link && it.ticket_link !== 'sold_out' ? `<a class="btn btn-sm btn-primary ticket-btn" href="${escAttr(it.ticket_link)}" target="_blank">Buy Ticket</a>` : `<span class="text-danger small">Sold Out</span>`}
          </div>
        </div>
      `;

      attachDragHandlers(card);
      cardDeck.appendChild(card);
    });
  }

  // Lightweight pointer-drag swipe handlers
  function attachDragHandlers(card) {
    let startX = 0, startY = 0, currentX = 0, currentY = 0, dragging = false;
    const threshold = 120;

    const setTransform = (x, y, rot) => {
      card.style.transform = `translateX(calc(-50% + ${x}px)) translateY(${y}px) rotate(${rot}deg)`;
    };

    card.addEventListener('pointerdown', (ev) => {
      if (ev.target.closest && ev.target.closest('.ticket-btn')) return;
      card.setPointerCapture(ev.pointerId);
      startX = ev.clientX; startY = ev.clientY; dragging = true; card.style.transition = 'none';
    });

    card.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      currentX = ev.clientX - startX; currentY = ev.clientY - startY;
      setTransform(currentX, currentY, currentX / 20);
      if (Math.abs(currentX) > threshold) card.classList.toggle('like', currentX > 0);
      else card.classList.remove('like', 'nope');
    });

    const finish = (ev) => {
      if (!dragging) return; dragging = false; try { card.releasePointerCapture(ev.pointerId); } catch(e){}
      const dx = currentX, dy = currentY;
      if (Math.abs(dx) > threshold) {
        const toRight = dx > 0;
        const offX = (toRight ? 1 : -1) * (window.innerWidth + 200);
        card.style.transition = 'transform 300ms ease, opacity 300ms ease';
        setTransform(offX, dy, toRight ? 30 : -30); card.style.opacity = '0.95';
        setTimeout(() => {
          const payload = JSON.parse(card.dataset.payload || '{}');
          const liked = dx > 0;
          (liked ? window._swipeResults.likes : window._swipeResults.dislikes).push(payload);
          window._swipeLog.push({ id: payload.id, liked, payload });
          card.remove(); if (cardDeck.querySelectorAll('.swipe-card').length === 0) renderSwipeSummary();
        }, 300);
      } else {
        card.style.transition = 'transform 300ms ease'; setTransform(0,0,0);
      }
    };

    card.addEventListener('pointerup', finish);
    card.addEventListener('pointercancel', finish);
    card.addEventListener('lostpointercapture', finish);
  }

  function renderSwipeSummary() {
    const wrapper = document.getElementById('swipeSummary');
    if (!wrapper) return;
    wrapper.classList.remove('d-none');
    const final = {};
    (window._swipeLog || []).forEach(e => { if (e && typeof e.id !== 'undefined') final[e.id] = Object.assign({}, e.payload || {}, { liked: !!e.liked }); });
    // fallback
    if (Object.keys(final).length === 0) {
      (window._swipeResults.dislikes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: false }); });
      (window._swipeResults.likes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: true }); });
    }
    const rows = Object.values(final);
    let html = `<h4>Swipe Summary</h4><table class="table table-striped"><thead><tr><th>Title</th><th>Show Date</th><th>Show Time</th><th>Day</th><th>Director</th><th>Year</th><th>Runtime</th><th>Format</th><th>Tickets</th><th>Liked</th></tr></thead><tbody>`;
    rows.forEach(m => {
      const liked = m.liked ? 'Yes' : 'No';
      html += `<tr><td>${esc(m.title)}</td><td>${esc(m.showdate)}</td><td>${esc(m.showtime)}</td><td>${esc(m.show_day)}</td><td>${esc(m.director)}</td><td>${esc(m.year)}</td><td>${esc(m.runtime)}</td><td>${esc(m.format)}</td><td>${m.ticket_link && m.ticket_link !== 'sold_out' ? `<a class="btn btn-sm btn-primary" href="${escAttr(m.ticket_link)}" target="_blank">${esc(m.cinema||'Tickets')}</a>` : '<span class="text-danger">Sold Out</span>'}</td><td>${liked}</td></tr>`;
    });
    html += '</tbody></table>';
    wrapper.innerHTML = html; wrapper.scrollIntoView({ behavior: 'smooth' });
  }

  // form submit
  if (form) {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const mood = (moodInput && moodInput.value || '').trim();
      if (!mood) { if (errEl) { errEl.textContent = 'Please enter a mood.'; errEl.classList.remove('d-none'); } return; }
      if (errEl) errEl.classList.add('d-none');
      submitBtn.disabled = true; const original = submitBtn.textContent; submitBtn.textContent = 'Thinking...';
      try {
        const res = await fetch('/api/recommend', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mood }) });
        const data = await res.json();
        if (!res.ok) { const msg = (data && data.error) ? data.error : 'Request failed'; if (errEl) { errEl.textContent = msg; errEl.classList.remove('d-none'); } return; }
        renderCardDeck(Array.isArray(data) ? data : []);
        if (resultWrapper) resultWrapper.classList.remove('d-none'); resultWrapper && resultWrapper.scrollIntoView({ behavior: 'smooth' });
      } catch (e) {
        if (errEl) { errEl.textContent = 'Network error. Try again.'; errEl.classList.remove('d-none'); }
      } finally { submitBtn.disabled = false; submitBtn.textContent = original; }
    });
  }

  // clear button
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      clearCardDeck(); if (resultWrapper) resultWrapper.classList.add('d-none'); if (moodInput) moodInput.value = ''; if (errEl) errEl.classList.add('d-none');
    });
  }
});
