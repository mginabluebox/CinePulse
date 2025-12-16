document.addEventListener('DOMContentLoaded', () => {
    // Cache commonly used DOM nodes
    const form = document.getElementById('recommendForm');
    const errEl = document.getElementById('recommendError');
    const resultWrapper = document.getElementById('recommendResultWrapper');
    const clearBtn = document.getElementById('clearRecommend');
    const submitBtn = document.getElementById('submitRecommend');
    const likedInput = document.getElementById('likedMovies');
    const moodInput = document.getElementById('mood');
    const cardDeck = document.getElementById('cardDeck');

    // Runtime storage for swipe results. _swipeLog keeps chronological actions so the latest action wins.
    window._swipeResults = { likes: [], dislikes: [] };
    window._swipeLog = [];

    // Utility: escape HTML content when inserting into the DOM
    function escapeHtml(s) {
      return String(s || '').replace(/[&<>\"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
    }
    function escapeAttr(s) { return encodeURI(String(s || '')); }

    // Clear current deck and reset runtime swipe data
    function clearCardDeck() {
      if (!cardDeck) return;
      cardDeck.innerHTML = '<div id="noRecs" class="text-muted">No recommendations yet — submit the form above.</div>';
      window._swipeResults = { likes: [], dislikes: [] };
      window._swipeLog = [];
      const summary = document.getElementById('swipeSummary');
      if (summary) summary.classList.add('d-none');
    }

    // Renders the card deck from an array of recommendation objects.
    // Resets runtime swipe data for each new deck to avoid mixing across sessions.
    function renderCardDeck(items) {
      if (!cardDeck) return;
      clearCardDeck();
      if (!items || items.length === 0) {
        cardDeck.innerHTML = '<div id="noRecs" class="text-muted">No recommendations found.</div>';
        return;
      }

      // reset swipe storage for this new run
      window._swipeResults = { likes: [], dislikes: [] };
      window._swipeLog = [];

      // create cards reversed so the first item appears on top
      const rev = items.slice().reverse();
      rev.forEach((it, idx) => {
        const card = document.createElement('div');
        card.className = 'swipe-card';
        card.style.zIndex = 100 + idx;
        // store payload so we can reconstruct the summary after swiping
        try { card.dataset.payload = JSON.stringify(it); } catch (e) { card.dataset.payload = '{}'; }

        card.innerHTML = `
          <div>
            <div class="title">${escapeHtml(it.title || '')}</div>
            <div class="reason">${escapeHtml(it.reason || '')}</div>
            <div class="synopsis">${escapeHtml(it.synopsis || '')}</div>
          </div>
          <div>
            <div class="meta">${escapeHtml(it.showdate || '')} ${escapeHtml(it.showtime || '')} at ${escapeHtml(it.cinema || '')}</div>
            <div class="d-flex justify-content-end">
              ${it.ticket_link && it.ticket_link !== 'sold_out' ? `<a class="btn btn-sm btn-primary ticket-btn" href="${escapeAttr(it.ticket_link)}" target="_blank">Buy Ticket</a>` : `<span class="text-danger small">Sold Out</span>`}
            </div>
          </div>
        `;

        // attach pointer-based drag handlers
        attachDragHandlers(card);
        cardDeck.appendChild(card);
      });
    }

    // Pointer-drag swipe logic for a single card.
    // Uses pointer events for touch/mouse compatibility and stores the swipe result.
    function attachDragHandlers(card) {
      let pointerId = null;
      let startX = 0, startY = 0;
      let currentX = 0, currentY = 0;
      let isDragging = false;
      const threshold = 120; // px needed to commit a swipe

      function setTransform(x, y, rot) {
        // Preserve the initial centering translateX(-50%) while applying the
        // runtime drag offset. Using calc keeps the card centered when x=0
        // and allows pixel offsets when dragging.
        card.style.transform = `translateX(calc(-50% + ${x}px)) translateY(${y}px) rotate(${rot}deg)`;
      }

      card.addEventListener('pointerdown', (ev) => {
        // prevent dragging when user clicks the ticket button
        if (ev.target.closest('.ticket-btn')) return;
        card.setPointerCapture(ev.pointerId);
        pointerId = ev.pointerId;
        startX = ev.clientX;
        startY = ev.clientY;
        isDragging = true;
        card.style.transition = 'none';
      });

      card.addEventListener('pointermove', (ev) => {
        if (!isDragging || ev.pointerId !== pointerId) return;
        currentX = ev.clientX - startX;
        currentY = ev.clientY - startY;
        const rot = currentX / 20;
        setTransform(currentX, currentY, rot);
        // simple visual cue classes
        if (Math.abs(currentX) > threshold) {
          card.classList.toggle('like', currentX > 0);
          card.classList.toggle('nope', currentX < 0);
        } else {
          card.classList.remove('like', 'nope');
        }
      });

      function commitSwipe(dx, dy) {
        const toRight = dx > 0;
        const offX = (toRight ? 1 : -1) * (window.innerWidth + 200);
  card.style.transition = 'transform 300ms ease, opacity 300ms ease';
  // Use setTransform so the -50% centering is preserved during the
  // off-screen animation.
  setTransform(offX, dy, toRight ? 30 : -30);
        card.style.opacity = '0.95';

        setTimeout(() => {
          // push payload into runtime structures
          const payloadText = card.dataset.payload || '{}';
          let payload = {};
          try { payload = JSON.parse(payloadText); } catch (e) { payload = {}; }
          const liked = dx > 0;
          if (liked) window._swipeResults.likes.push(payload); else window._swipeResults.dislikes.push(payload);
          try { window._swipeLog.push({ id: payload.id, liked: liked, payload: payload }); } catch (e) {}
          card.remove();
          checkDeckEmptyAndShowSummary();
        }, 300);
      }

      function endDrag(ev) {
        if (!isDragging || ev.pointerId !== pointerId) return;
        isDragging = false;
        card.releasePointerCapture(pointerId);
        const dx = currentX;
        const dy = currentY;
        if (Math.abs(dx) > threshold) commitSwipe(dx, dy);
        else {
          // snap back
          card.style.transition = 'transform 300ms ease';
          setTransform(0, 0, 0);
          card.classList.remove('like', 'nope');
        }
      }

      card.addEventListener('pointerup', endDrag);
      card.addEventListener('pointercancel', endDrag);
      card.addEventListener('lostpointercapture', endDrag);
    }

    // If the deck is empty, show a summary table built from the chronological swipe log.
    function checkDeckEmptyAndShowSummary() {
      if (!cardDeck) return;
      const remaining = cardDeck.querySelectorAll('.swipe-card');
      if (remaining.length === 0) {
        renderSwipeSummary();
      }
    }

    // Build and render a summary table. For any duplicate movie id in the log, the latest action wins.
    function renderSwipeSummary() {
      const wrapper = document.getElementById('swipeSummary');
      if (!wrapper) return;
      wrapper.classList.remove('d-none');

      const log = window._swipeLog || [];
      const finalMap = {};
      // apply chronological log so last entry wins
      log.forEach(entry => {
        if (!entry || typeof entry.id === 'undefined') return;
        finalMap[entry.id] = Object.assign({}, entry.payload || {}, { liked: !!entry.liked });
      });

      // If there was no log (edge case), fall back to likes/dislikes arrays
      if (Object.keys(finalMap).length === 0) {
        (window._swipeResults.dislikes || []).forEach(i => { if (i && typeof i.id !== 'undefined') finalMap[i.id] = Object.assign({}, i, { liked: false }); });
        (window._swipeResults.likes || []).forEach(i => { if (i && typeof i.id !== 'undefined') finalMap[i.id] = Object.assign({}, i, { liked: true }); });
      }

      const rows = Object.values(finalMap);

      let html = `\n      <h4>Swipe Summary</h4>\n      <table class="table table-striped">\n        <thead>\n          <tr>\n            <th>Title</th>\n            <th>Show Date</th>\n            <th>Show Time</th>\n            <th>Day</th>\n            <th>Director</th>\n            <th>Year</th>\n            <th>Runtime</th>\n            <th>Format</th>\n            <th>Tickets</th>\n            <th>Liked</th>\n          </tr>\n        </thead>\n        <tbody>\n    `;

      rows.forEach((movie) => {
        const liked = movie.liked ? 'Yes' : 'No';
        html += `\n        <tr>\n          <td>${escapeHtml(movie.title || '')}</td>\n          <td>${escapeHtml(movie.showdate || '')}</td>\n          <td>${escapeHtml(movie.showtime || '')}</td>\n          <td>${escapeHtml(movie.show_day || '')}</td>\n          <td>${escapeHtml(movie.director || '')}</td>\n          <td>${escapeHtml(movie.year || '')}</td>\n          <td>${escapeHtml(movie.runtime || '')}</td>\n          <td>${escapeHtml(movie.format || '')}</td>\n          <td>${movie.ticket_link && movie.ticket_link !== 'sold_out' ? `<a class="btn btn-sm btn-primary" href="${escapeAttr(movie.ticket_link)}" target="_blank">${escapeHtml(movie.cinema||'Tickets')}</a>` : '<span class="text-danger">Sold Out</span>'}</td>\n          <td>${liked}</td>\n        </tr>\n      `;
      });

      html += '</tbody></table>';
      wrapper.innerHTML = html;
      wrapper.scrollIntoView({ behavior: 'smooth' });
    }

    // wire up form and clear button
    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const liked = (likedInput?.value || '').trim();
      const mood = (moodInput?.value || '').trim();
      if (!liked && !mood) {
        if (errEl) { errEl.textContent = 'Please enter something you liked or a mood.'; errEl.classList.remove('d-none'); }
        return;
      }
      if (errEl) errEl.classList.add('d-none');

      submitBtn.disabled = true;
      const origText = submitBtn.textContent;
      submitBtn.textContent = 'Thinking...';

      try {
        const res = await fetch('/api/recommend', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ liked_movies: liked, mood: mood })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || JSON.stringify(data));
        renderCardDeck(Array.isArray(data) ? data : []);
        if (resultWrapper) resultWrapper.classList.remove('d-none');
        resultWrapper?.scrollIntoView({ behavior: 'smooth' });
      } catch (err) {
        if (errEl) { errEl.textContent = err.message || 'Network error. Try again.'; errEl.classList.remove('d-none'); }
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = origText;
      }
    });

    clearBtn?.addEventListener('click', () => {
      clearCardDeck();
      if (resultWrapper) resultWrapper.classList.add('d-none');
      if (likedInput) likedInput.value = '';
      if (moodInput) moodInput.value = '';
      if (errEl) errEl.classList.add('d-none');
    });
  });
