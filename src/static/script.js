document.addEventListener('DOMContentLoaded', () => {
  // Movie picks (embedding-based). Legacy /api/recommend UI is archived.
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

  // Archived: legacy showtime-based swipe UI removed.

  // form submit
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

  function attachMovieDragHandlers(card) {
    let startX = 0, startY = 0, currentX = 0, currentY = 0, dragging = false;
    const threshold = 120;

    const setTransform = (x, y, rot) => {
      card.style.transform = `translateX(calc(-50% + ${x}px)) translateY(${y}px) rotate(${rot}deg)`;
    };

    card.addEventListener('dragstart', (ev) => ev.preventDefault());

    card.addEventListener('pointerdown', (ev) => {
      if (ev.target.closest && ev.target.closest('a')) return;
      card.setPointerCapture(ev.pointerId);
      startX = ev.clientX; startY = ev.clientY; dragging = true; card.style.transition = 'none';
    });

    card.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      currentX = ev.clientX - startX; currentY = ev.clientY - startY;
      setTransform(currentX, currentY, currentX / 20);
      if (Math.abs(currentX) > threshold) {
        if (currentX > 0) {
          card.classList.add('like');
          card.classList.remove('nope');
        } else {
          card.classList.add('nope');
          card.classList.remove('like');
        }
      } else {
        card.classList.remove('like', 'nope');
      }
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
    if (!Array.isArray(items) && items && typeof items === 'object') {
      console.warn('movie render: expected array, got object; coercing to array of values');
      items = Object.values(items);
    }
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

      const imgUrl = it.scraped_image_url || it.image_url;
      const imgHtml = imgUrl ? `<div class="card-img-wrapper mb-2"><img src="${escAttr(imgUrl)}" alt="${esc(it.title)} poster" class="swipe-card-img"></div>` : '';
      const cinemas = Array.isArray(it.cinemas) ? it.cinemas : [];
      let cinemaHtml = '';
      // showtimes removed from card view per request

      const score = typeof it.similarity === 'number' ? it.similarity.toFixed(2) : '–';
      const metaBits = [];
      if (it.year) metaBits.push(esc(it.year));
      if (it.director) metaBits.push(esc(it.director));
      if (score !== '–') metaBits.push(`Relevance Score: ${score}`);
      const metaLine = metaBits.join(' • ');
      card.innerHTML = `
        <div>
          ${imgHtml}
          <div class="title">${esc(it.title)}</div>
          <div class="small text-muted">${metaLine}</div>
          <div class="reason">${esc(it.reason || '')}</div>
          <div class="synopsis">${esc(it.synopsis || '')}</div>
        </div>
      `;

      attachMovieDragHandlers(card);
      movieCards.appendChild(card);
    });
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
