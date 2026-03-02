document.addEventListener('DOMContentLoaded', () => {
  // Minimal but complete recommendation UI script.
  const form = document.getElementById('recommendForm');
  const errEl = document.getElementById('recommendError');
  const resultWrapper = document.getElementById('recommendResultWrapper');
  const clearBtn = document.getElementById('clearRecommend');
  const submitBtn = document.getElementById('submitRecommend');
  const moodInput = document.getElementById('mood');
  const cardDeck = document.getElementById('cardDeck');

  // Movie-based recommendation tab elements
  const movieForm = document.getElementById('movieRecommendForm');
  const movieErrEl = document.getElementById('movieRecommendError');
  const movieResultWrapper = document.getElementById('movieRecommendResultWrapper');
  const movieClearBtn = document.getElementById('clearMovieRecommend');
  const movieSubmitBtn = document.getElementById('submitMovieRecommend');
  const movieMoodInput = document.getElementById('movieMood');
  const movieCards = document.getElementById('movieCards');
  const movieSwipeSummary = document.getElementById('movieSwipeSummary');
  const movieTopHeader = document.getElementById('movieTopHeader');
  const movieSwipeHint = document.getElementById('movieSwipeHint');

  // Simple runtime storage for swipes
  window._swipeResults = { likes: [], dislikes: [] };
  window._swipeLog = [];
  const movieSwipeState = { likes: [], dislikes: [], log: [] };

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

  // --- Movie Picks (embedding-based) ---
  function clearMovieCards() {
    if (movieCards) movieCards.innerHTML = '<div id="noMovieRecs" class="text-muted">No recommendations yet — submit the form above.</div>';
    movieSwipeState.likes = [];
    movieSwipeState.dislikes = [];
    movieSwipeState.log = [];
    if (movieSwipeSummary) { movieSwipeSummary.classList.add('d-none'); movieSwipeSummary.innerHTML = ''; }
    if (movieErrEl) movieErrEl.classList.add('d-none');
    if (movieTopHeader) movieTopHeader.classList.remove('d-none');
    if (movieSwipeHint) movieSwipeHint.classList.remove('d-none');
    if (movieTopHeader && movieTopHeader.parentElement) movieTopHeader.parentElement.classList.remove('d-none');
    if (movieCards) movieCards.classList.remove('d-none');
  }

  function renderMovieSwipeSummary() {
    if (!movieSwipeSummary) return;
    movieSwipeSummary.classList.remove('d-none');
    const final = {};
    (movieSwipeState.log || []).forEach(e => { if (e && typeof e.id !== 'undefined') final[e.id] = Object.assign({}, e.payload || {}, { liked: !!e.liked }); });
    if (Object.keys(final).length === 0) return;

    let html = '<h5>Swipe Summary</h5>';
    html += '<table class="table table-striped"><thead><tr><th>Title</th><th>Reason</th><th>Showtimes (max 5)</th><th>Liked</th></tr></thead><tbody>';
    Object.values(final).forEach((m) => {
      const showHtml = (Array.isArray(m.cinemas) ? m.cinemas : []).map(c => {
        const sts = Array.isArray(c.showtimes) ? c.showtimes : [];
        const times = sts.map(st => `${esc(st.showdate)} ${esc(st.showtime)}`).join('<br>');
        return `<div><strong>${esc(c.cinema)}</strong><div class="small">${times || 'No upcoming showtimes'}</div></div>`;
      }).join('');
      html += `<tr><td>${esc(m.title)}</td><td>${esc(m.reason || '')}</td><td>${showHtml}</td><td>${m.liked ? 'Yes' : 'No'}</td></tr>`;
    });
    html += '</tbody></table>';
    movieSwipeSummary.innerHTML = html;
    movieSwipeSummary.scrollIntoView({ behavior: 'smooth' });
  }

  function attachMovieDragHandlers(card) {
    let startX = 0, startY = 0, currentX = 0, currentY = 0, dragging = false;
    const threshold = 120;

    const setTransform = (x, y, rot) => {
      card.style.transform = `translateX(calc(-50% + ${x}px)) translateY(${y}px) rotate(${rot}deg)`;
    };

    card.addEventListener('pointerdown', (ev) => {
      if (ev.target.closest && ev.target.closest('a')) return;
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
          (liked ? movieSwipeState.likes : movieSwipeState.dislikes).push(payload);
          movieSwipeState.log.push({ id: payload.id, liked, payload });
          card.remove();
          if (movieCards && movieCards.querySelectorAll('.swipe-card').length === 0) renderMovieSwipeSummary();
        }, 300);
      } else {
        card.style.transition = 'transform 300ms ease'; setTransform(0,0,0);
      }
    };

    card.addEventListener('pointerup', finish);
    card.addEventListener('pointercancel', finish);
    card.addEventListener('lostpointercapture', finish);
  }

  function renderMovieCards(items) {
    clearMovieCards();
    if (!movieCards || !Array.isArray(items) || items.length === 0) return;
    movieCards.innerHTML = '';
    if (movieTopHeader) movieTopHeader.classList.remove('d-none');
    if (movieTopHeader && movieTopHeader.parentElement) movieTopHeader.parentElement.classList.remove('d-none');
    if (movieSwipeHint) movieSwipeHint.classList.remove('d-none');
    if (movieCards) movieCards.classList.remove('d-none');

    // render top item last so the first recommendation appears on top
    items.slice().reverse().forEach((it, idx) => {
      const card = document.createElement('div');
      card.className = 'swipe-card';
      card.style.zIndex = 100 + idx;
      const payload = Object.assign({}, it || {}, { id: it.movie_id || it.id });
      card.dataset.payload = JSON.stringify(payload);

      const cinemas = Array.isArray(it.cinemas) ? it.cinemas : [];
      let cinemaHtml = '';
      cinemas.forEach((c) => {
        const showtimes = Array.isArray(c.showtimes) ? c.showtimes : [];
        const timesList = showtimes.map(st => `<li>${esc(st.showdate)} ${esc(st.showtime)}${st.ticket_link && st.ticket_link !== 'sold_out' ? ` – <a href="${escAttr(st.ticket_link)}" target="_blank">Tickets</a>` : ' – <span class="text-danger">Sold Out</span>'}</li>`).join('');
        cinemaHtml += `
          <div class="mb-2">
            <div class="fw-bold">${esc(c.cinema)}</div>
            <ul class="mb-0">${timesList || '<li class="text-muted">No upcoming showtimes</li>'}</ul>
          </div>
        `;
      });

      const score = typeof it.similarity === 'number' ? it.similarity.toFixed(2) : '–';
      card.innerHTML = `
        <div>
          <div class="title">${esc(it.title)}</div>
          <div class="small text-muted">Similarity ${score}${it.year ? ` • ${esc(it.year)}` : ''}</div>
          <div class="reason">${esc(it.reason || '')}</div>
          <div class="synopsis">${esc(it.synopsis || '')}</div>
        </div>
        <div class="mt-2">
          ${cinemaHtml || '<div class="text-muted">No upcoming showtimes</div>'}
        </div>
      `;

      attachMovieDragHandlers(card);
      movieCards.appendChild(card);
    });
  }

  function attachMovieDragHandlers(card) {
    let startX = 0, startY = 0, currentX = 0, currentY = 0, dragging = false;
    const threshold = 120;

    const setTransform = (x, y, rot) => {
      card.style.transform = `translateX(calc(-50% + ${x}px)) translateY(${y}px) rotate(${rot}deg)`;
    };

    card.addEventListener('pointerdown', (ev) => {
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
          (liked ? movieSwipeState.likes : movieSwipeState.dislikes).push(payload);
          movieSwipeState.log.push({ id: payload.id, liked, payload });
          card.remove();
          if (movieCards && movieCards.querySelectorAll('.swipe-card').length === 0) {
            renderMovieSwipeSummary();
          }
        }, 300);
      } else {
        card.style.transition = 'transform 300ms ease'; setTransform(0,0,0);
      }
    };

    card.addEventListener('pointerup', finish);
    card.addEventListener('pointercancel', finish);
    card.addEventListener('lostpointercapture', finish);
  }

  function renderMovieSwipeSummary() {
    if (!movieSwipeSummary) return;
    const final = {};
    (movieSwipeState.log || []).forEach(e => { if (e && typeof e.id !== 'undefined') final[e.id] = Object.assign({}, e.payload || {}, { liked: !!e.liked }); });
    if (Object.keys(final).length === 0) {
      (movieSwipeState.dislikes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: false }); });
      (movieSwipeState.likes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: true }); });
    }
    const rows = Object.values(final);
    let html = `<h5>Swipe Summary</h5><table class="table table-striped"><thead><tr><th>Title</th><th>Reason</th><th>Liked</th><th>Showtimes</th></tr></thead><tbody>`;
    rows.forEach(m => {
      const liked = m.liked ? 'Yes' : 'No';
      const st = Array.isArray(m.showtimes) ? m.showtimes.slice(0,5) : [];
      const stHtml = st.map(s => {
        const link = s.ticket_link && s.ticket_link !== 'sold_out'
          ? `<a class="btn btn-sm btn-primary" href="${escAttr(s.ticket_link)}" target="_blank">${esc(s.cinema || 'Tickets')}</a>`
          : '<span class="text-danger">Sold Out</span>';
        const dow = s.show_day ? ` (${esc(s.show_day)})` : '';
        return `<div class="mb-1">${esc(s.showdate)}${dow} ${esc(s.showtime)} ${link}</div>`;
      }).join('') || '<span class="text-muted">None</span>';
      html += `<tr><td>${esc(m.title)}</td><td>${esc(m.reason || '')}</td><td>${liked}</td><td>${stHtml}</td></tr>`;
    });
    html += '</tbody></table>';
    movieSwipeSummary.innerHTML = html;
    movieSwipeSummary.classList.remove('d-none');
    if (movieCards) movieCards.classList.add('d-none');
    if (movieTopHeader) movieTopHeader.classList.add('d-none');
    if (movieTopHeader && movieTopHeader.parentElement) movieTopHeader.parentElement.classList.add('d-none');
    if (movieSwipeHint) movieSwipeHint.classList.add('d-none');
    movieSwipeSummary.scrollIntoView({ behavior: 'smooth' });
  }

  if (movieForm) {
    movieForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const mood = (movieMoodInput && movieMoodInput.value || '').trim();
      if (!mood) { if (movieErrEl) { movieErrEl.textContent = 'Please enter a mood.'; movieErrEl.classList.remove('d-none'); } return; }
      if (movieErrEl) movieErrEl.classList.add('d-none');
      if (movieSubmitBtn) { movieSubmitBtn.disabled = true; movieSubmitBtn.textContent = 'Thinking...'; }
      try {
        const res = await fetch('/api/recommend_movies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mood }) });
        const data = await res.json();
        if (!res.ok) { const msg = (data && data.error) ? data.error : 'Request failed'; if (movieErrEl) { movieErrEl.textContent = msg; movieErrEl.classList.remove('d-none'); } return; }
        renderMovieCards(Array.isArray(data) ? data : []);
        if (movieResultWrapper) movieResultWrapper.classList.remove('d-none');
        movieResultWrapper && movieResultWrapper.scrollIntoView({ behavior: 'smooth' });
      } catch (e) {
        if (movieErrEl) { movieErrEl.textContent = 'Network error. Try again.'; movieErrEl.classList.remove('d-none'); }
      } finally {
        if (movieSubmitBtn) { movieSubmitBtn.disabled = false; movieSubmitBtn.textContent = 'Get movie picks'; }
      }
    });
  }

  if (movieClearBtn) {
    movieClearBtn.addEventListener('click', () => {
      clearMovieCards();
      if (movieResultWrapper) movieResultWrapper.classList.add('d-none');
      if (movieMoodInput) movieMoodInput.value = '';
    });
  }
});
