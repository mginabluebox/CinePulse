document.addEventListener('DOMContentLoaded', () => {
  // Movie picks (embedding-based). Legacy /api/recommend UI is archived.
  const movieForm = document.getElementById('movieRecommendForm');
  const movieErrEl = document.getElementById('movieRecommendError');
  const movieResultWrapper = document.getElementById('movieRecommendResultWrapper');
  const movieClearBtn = document.getElementById('clearMovieRecommend');
  const movieSubmitBtn = document.getElementById('submitMovieRecommend');
  const moviePreferenceInput = document.getElementById('moviePreference');
  const movieCards = document.getElementById('movieCards');
  const movieSwipeSummary = document.getElementById('movieSwipeSummary');
  if (movieSwipeSummary) {
    movieSwipeSummary.addEventListener('click', (e) => {
      if (e.target.closest('.cp-details-arrow')) return;
      const trigger = e.target.closest('.cp-film-banner-trigger.cp-expandable');
      if (!trigger) return;
      const banner = trigger.closest('.cp-film-banner');
      const isExpanded = banner.classList.contains('expanded');
      movieSwipeSummary.querySelectorAll('.cp-film-banner.expanded').forEach(b => {
        b.classList.remove('expanded');
        b.querySelectorAll('.cp-banner-synopsis-inline').forEach(s => s.classList.remove('synopsis-visible'));
      });
      if (!isExpanded) {
        banner.classList.add('expanded');
        setTimeout(() => {
          banner.querySelectorAll('.cp-banner-synopsis-inline').forEach(s => s.classList.add('synopsis-visible'));
        }, 380);
      }
    });
  }
  const movieTopHeader = document.getElementById('movieTopHeader');
  const movieSwipeHint = document.getElementById('movieSwipeHint');

  // Showtimes search (semantic)
  const showtimeSearchForm = document.getElementById('showtimeSearchForm');
  const showtimeSearchInput = document.getElementById('showtimeSearchInput');
  const showtimeSearchButton = document.getElementById('showtimeSearchButton');
  const showtimeSearchBtnOrig = showtimeSearchButton ? showtimeSearchButton.innerHTML : 'Search';
  const showtimeInputPlaceholderOrig = showtimeSearchInput ? showtimeSearchInput.placeholder : 'Search films…';

  function showSearchInputError(msg) {
    if (!showtimeSearchInput) return;
    showtimeSearchInput.placeholder = msg;
    showtimeSearchInput.classList.add('cp-input-error');
    showtimeSearchInput.value = '';
  }
  function clearSearchInputError() {
    if (!showtimeSearchInput) return;
    showtimeSearchInput.placeholder = showtimeInputPlaceholderOrig;
    showtimeSearchInput.classList.remove('cp-input-error');
  }
  const showtimeAccordion = document.getElementById('showtimeAccordion');
  const showtimeEmptyState = document.getElementById('showtimeEmptyState');
  const initialShowtimeHTML = showtimeAccordion ? showtimeAccordion.innerHTML : '';
  const showtimePagination = document.getElementById('showtimePagination');
  const showtimePageInfo = document.getElementById('showtimePageInfo');
  const showtimePrevPage = document.getElementById('showtimePrevPage');
  const showtimeNextPage = document.getElementById('showtimeNextPage');
  const showtimePageInput = document.getElementById('showtimePageInput');
  const showtimePageGo = document.getElementById('showtimePageGo');
  const initialShowtimeDataEl = document.getElementById('initialShowtimesData');
  let initialShowtimeData = [];
  try {
    if (initialShowtimeDataEl && initialShowtimeDataEl.textContent) {
      initialShowtimeData = JSON.parse(initialShowtimeDataEl.textContent) || [];
    }
  } catch (e) {
    initialShowtimeData = [];
  }
  const SHOWTIME_PAGE_SIZE = 10;
  let showtimeResults = null;
  let showtimePage = 1;
  let showtimeTotalPages = 1;

  function getFilteredShowtimeResults() {
    if (!Array.isArray(showtimeResults)) return [];
    if (typeof selectedCinemas === 'undefined' || selectedCinemas.size === 0) return showtimeResults;
    return showtimeResults.filter(m =>
      (m.showtimes || []).some(s => s.cinema && selectedCinemas.has(s.cinema))
    );
  }
  let currentRunId = null;

  // Swipe feedback icons — change here to update both the card overlay and summary badges
  const _svgAttrs = 'xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  const SWIPE_ICON_LIKE    = `<svg ${_svgAttrs} style="color:#5cb85c"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>`;
  const SWIPE_ICON_DISLIKE = `<svg ${_svgAttrs} style="color:#c42b2b"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L13 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>`;

  // Simple runtime storage for swipes
  window._swipeResults = { likes: [], dislikes: [] };
  window._swipeLog = [];
  const movieSwipeState = { likes: [], dislikes: [], log: [] };
  const swipeStartTimes = new WeakMap();

  function ensureSessionToken() {
    const key = 'cinepulse_session_token';
    let tok = localStorage.getItem(key);
    if (!tok) {
      tok = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
      localStorage.setItem(key, tok);
    }
    return tok;
  }
  const sessionToken = ensureSessionToken();

  const esc = (s) => String(s || '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const escAttr = (s) => encodeURI(String(s || ''));

  // Render title with cinema suffix styled separately; detailsLink makes the cinema+arrow clickable
  function titleHtml(title, cinemas, detailsLink) {
    if (!cinemas || !cinemas.length) return esc(title);
    const cinemaText = ` @ ${esc(cinemas.join(' & '))}`;
    if (detailsLink) {
      const onclick = `event.stopPropagation();window.open('${escAttr(detailsLink)}','_blank')`;
      return `${esc(title)}<span class="cp-title-cinema" onclick="${onclick}">${cinemaText}<span class="cp-details-arrow"> ↗</span></span>`;
    }
    return `${esc(title)}<span class="cp-title-cinema">${cinemaText}</span>`;
  }

  // --- Shared showtime rendering (consistent with landing page) ---
  function renderShowtimeBtns(showtimes) {
    if (!Array.isArray(showtimes) || showtimes.length === 0) return '';
    // Group by date
    const order = [];
    const groups = {};
    showtimes.forEach(st => {
      const date = st.showdate || '';
      if (!groups[date]) { groups[date] = { label: st.show_day ? `${st.show_day}, ${date}` : date, sts: [] }; order.push(date); }
      groups[date].sts.push(st);
    });
    return order.map(date => {
      const { label, sts } = groups[date];
      sts.sort((a, b) => _stMins(a.showtime) - _stMins(b.showtime));
    const btns = sts.map(st => {
        if (st.ticket_link === 'sold_out') {
          return `<span class="cp-time-btn sold-out"><span>${esc(st.showtime)}</span></span>`;
        }
        return `<a href="${escAttr(st.ticket_link)}" target="_blank" class="cp-time-btn">${esc(st.showtime)}</a>`;
      }).join('');
      return `<div class="cp-showtime-date-group"><span class="cp-showtime-date-label">${esc(label)}</span><div class="cp-film-times">${btns}</div></div>`;
    }).join('');
  }

  // --- Showtime period helpers (mirrors Python logic) ---
  function _stMins(t) {
    if (!t) return 9999;
    try {
      const parts = String(t).trim().toUpperCase().split(':');
      const h = parseInt(parts[0]);
      const rest = parts[1].split(/\s+/);
      const mn = parseInt(rest[0]);
      const ampm = rest[1] || null;
      let hh = h;
      if (ampm === 'PM' && h < 12) hh += 12;
      if (ampm === 'AM' && h === 12) hh = 0;
      return hh * 60 + mn;
    } catch(e) { return 9999; }
  }
  function _stPeriod(t) {
    const m = _stMins(t);
    return m < 720 ? 'morning' : m < 1020 ? 'afternoon' : 'evening';
  }

  // --- Render period-grouped time buttons (used in search banners) ---
  function renderPeriodTimes(showtimes) {
    const byPeriod = { morning: [], afternoon: [], evening: [] };
    (showtimes || []).slice()
      .sort((a, b) => _stMins(a.showtime) - _stMins(b.showtime))
      .forEach(st => byPeriod[_stPeriod(st.showtime)].push(st));
    return [['morning','Morning'],['afternoon','Afternoon'],['evening','Evening']].map(([key, label]) => {
      if (!byPeriod[key].length) return '';
      const btns = byPeriod[key].map(st =>
        st.ticket_link === 'sold_out'
          ? `<span class="cp-time-btn sold-out"><span>${esc(st.showtime)}</span></span>`
          : `<a href="${escAttr(st.ticket_link)}" target="_blank" class="cp-time-btn">${esc(st.showtime)}</a>`
      ).join('');
      return `<div class="cp-period-group"><span class="cp-period-label">${label}</span><div class="cp-film-times">${btns}</div></div>`;
    }).join('');
  }

  // Mirrors _week_panels.html render_film_banner macro.
  // opts.expandableEl: non-empty string → adds cp-expandable class AND provides the HTML content.
  function scoreItem(val, label, suffix = '') {
    return val ? `<div class="cp-score-item"><span class="cp-score-value">${esc(String(val))}${suffix}</span><span class="cp-score-label">${label}</span></div>` : '';
  }
  function renderFilmBanner(film, { titleContent, timesHtml = '', extraInfoHtml = '', expandableEl = '' }) {
    const imgHtml = film.image_url
      ? `<img src="${escAttr(film.image_url)}" alt="${esc(film.title)}" class="cp-film-thumb" loading="lazy" onerror="this.closest('.cp-film-thumb-wrap').style.display='none'">`
      : '';
    const metaParts = [];
    if (film.director) metaParts.push(esc(film.director));
    if (film.year) metaParts.push(esc(String(film.year)));
    if (film.runtime) metaParts.push(`${esc(String(film.runtime))} min`);
    const genresHtml = Array.isArray(film.tmdb_genres) && film.tmdb_genres.length
      ? `<div class="cp-film-genres">${film.tmdb_genres.slice(0, 3).map(g => `<span class="cp-genre-tag">${esc(g)}</span>`).join('')}</div>`
      : '';
    const scoresHtml = (film.imdb_rating || film.omdb_rt_score || film.omdb_metacritic_score)
      ? `<div class="cp-film-scores">${[
          scoreItem(film.imdb_rating, 'IMDb'),
          scoreItem(film.omdb_rt_score, 'RT', '%'),
          scoreItem(film.omdb_metacritic_score, 'MC'),
        ].filter(Boolean).join('')}</div>`
      : '';
    const expandSection = expandableEl
      ? `<div class="cp-banner-synopsis-inline">${expandableEl}</div>`
      : '';
    return `
      <div class="cp-film-banner">
        <div class="cp-film-banner-row">
          <div class="cp-film-banner-trigger${expandableEl ? ' cp-expandable' : ''}">
            <div class="cp-film-thumb-wrap">${imgHtml}</div>
            <div class="cp-film-info">
              <span class="cp-film-title">${titleContent}</span>
              ${genresHtml}
              <span class="cp-film-meta">${metaParts.join(' · ')}</span>
              ${extraInfoHtml}
            </div>
            ${scoresHtml}
          </div>
          ${timesHtml}
          ${expandSection}
        </div>
      </div>`;
  }

  // --- Showtime search rendering (banner style, consistent with calendar) ---
  function renderShowtimeAccordion(movies) {
    if (!showtimeAccordion) return;
    if (!Array.isArray(movies) || movies.length === 0) {
      showtimeAccordion.innerHTML = '';
      if (showtimeEmptyState) showtimeEmptyState.classList.remove('d-none');
      return;
    }
    if (showtimeEmptyState) showtimeEmptyState.classList.add('d-none');

    const html = movies.map((m) => {
      const cinemas = [...new Set((m.showtimes || []).map(s => s.cinema).filter(Boolean))];
      const detailsLink = (m.showtimes || []).map(s => s.details_link).find(Boolean) || '';
      const simHtml = typeof m.similarity === 'number'
        ? `<span class="cp-similarity">${Math.round(m.similarity * 100)}% match</span>`
        : '';
      const expandableEl = m.synopsis
        ? `<p class="cp-synopsis">${esc(m.synopsis)}</p>`
        : '';
      return renderFilmBanner(m, {
        titleContent: titleHtml(m.title, cinemas, detailsLink),
        timesHtml: `<div class="cp-showtime-groups">${renderShowtimeBtns(m.showtimes)}</div>`,
        extraInfoHtml: simHtml,
        expandableEl,
      });
    }).join('');

    showtimeAccordion.innerHTML = html;

    // Attach click handlers with auto-collapse
    showtimeAccordion.querySelectorAll('.cp-film-banner-trigger.cp-expandable').forEach(trigger => {
      trigger.addEventListener('click', () => {
        const banner = trigger.closest('.cp-film-banner');
        const isExpanded = banner.classList.contains('expanded');
        document.querySelectorAll('.cp-film-banner.expanded').forEach(b => {
          b.classList.remove('expanded');
          b.querySelectorAll('.cp-banner-synopsis-inline').forEach(s => s.classList.remove('synopsis-visible'));
        });
        if (!isExpanded) {
          banner.classList.add('expanded');
          setTimeout(() => {
            banner.querySelectorAll('.cp-banner-synopsis-inline').forEach(s => s.classList.add('synopsis-visible'));
          }, 380);
        }
      });
    });
  }

  function updateShowtimePagination(total, page, pageSize) {
    if (!showtimePagination || !showtimePageInfo || !showtimePrevPage || !showtimeNextPage) return;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    showtimeTotalPages = totalPages;
    if (total <= pageSize) {
      showtimePagination.classList.add('d-none');
      return;
    }
    showtimePagination.classList.remove('d-none');
    const start = (page - 1) * pageSize + 1;
    const end = Math.min(total, page * pageSize);
    showtimePageInfo.textContent = `Showing ${start}-${end} of ${total}`;
    showtimePrevPage.disabled = page <= 1;
    showtimeNextPage.disabled = page >= totalPages;
    if (showtimePageInput) {
      showtimePageInput.value = page;
      showtimePageInput.min = 1;
      showtimePageInput.max = totalPages;
    }
  }

  function renderShowtimePage(page) {
    if (!Array.isArray(showtimeResults) || showtimeResults.length === 0) {
      renderShowtimeAccordion([]);
      if (showtimePagination) showtimePagination.classList.add('d-none');
      return;
    }

    const filtered = getFilteredShowtimeResults();
    const total = filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / SHOWTIME_PAGE_SIZE));
    const nextPage = Math.min(Math.max(1, page || 1), totalPages);
    showtimePage = nextPage;

    const startIdx = (nextPage - 1) * SHOWTIME_PAGE_SIZE;
    const slice = filtered.slice(startIdx, startIdx + SHOWTIME_PAGE_SIZE);
    renderShowtimeAccordion(slice);
    updateShowtimePagination(total, nextPage, SHOWTIME_PAGE_SIZE);
  }
  window.renderShowtimePage = renderShowtimePage;

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

  function logFeedback(payload, liked, decisionMs) {
    const body = {
      run_id: currentRunId,
      movie_id: payload.movie_id || payload.id,
      liked: !!liked,
      decision_ms: decisionMs,
      session_token: sessionToken,
      similarity: payload.similarity,
      title: payload.title,
      year: payload.year,
    };
    fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(() => {});
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
      ev.preventDefault();
      if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
      card.setPointerCapture(ev.pointerId);
      startX = ev.clientX; startY = ev.clientY; dragging = true; card.style.transition = 'none';
      swipeStartTimes.set(card, Date.now());
    });

    card.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      ev.preventDefault();
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
          const startedAt = swipeStartTimes.get(card);
          const decisionMs = startedAt ? (Date.now() - startedAt) : undefined;
          logFeedback(payload, liked, decisionMs);
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
      const cinemaList = [...new Set((it.showtimes || []).map(s => s.cinema).filter(Boolean))];
      const imgHtml = imgUrl ? `<div class="card-img-wrapper mb-2"><img src="${escAttr(imgUrl)}" alt="${esc(it.title)} poster" class="swipe-card-img"></div>` : '';
      const metaBits = [];
      const metaParts = [];
      if (it.year) metaParts.push(esc(it.year));
      if (it.runtime) metaParts.push(`${esc(it.runtime)} min`);
      if (it.director) metaParts.push(esc(it.director));
      metaParts.forEach(p => metaBits.push(p));
      const metaLine = metaBits.join(' • ');
      card.innerHTML = `
        <div class="swipe-feedback-overlay swipe-feedback-like">${SWIPE_ICON_LIKE}</div>
        <div class="swipe-feedback-overlay swipe-feedback-nope">${SWIPE_ICON_DISLIKE}</div>
        <div>
          ${imgHtml}
          <div class="title">${titleHtml(it.title, cinemaList)}</div>
          <div class="small text-muted">${metaLine}</div>
          ${it.reason ? `<div class="reason"><strong>Why you might like it:</strong> ${esc(it.reason)}</div>` : ''}
          <div class="synopsis">${esc(it.synopsis || '')}</div>
        </div>
      `;

      attachMovieDragHandlers(card);
      movieCards.appendChild(card);
    });
  }

  function renderMovieSwipeSummary() {
    if (!movieSwipeSummary) return;
    const toTimestamp = (showdate, showtime) => {
      if (!showdate) return Number.POSITIVE_INFINITY;
      const mins = _stMins(showtime);
      const hh = mins === 9999 ? 0 : Math.floor(mins / 60);
      const mm = mins === 9999 ? 0 : mins % 60;
      const iso = `${showdate}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00`;
      const ts = Date.parse(iso);
      return Number.isFinite(ts) ? ts : Number.POSITIVE_INFINITY;
    };

    const final = {};
    (movieSwipeState.log || []).forEach(e => { if (e && typeof e.id !== 'undefined') final[e.id] = Object.assign({}, e.payload || {}, { liked: !!e.liked }); });
    if (Object.keys(final).length === 0) {
      (movieSwipeState.dislikes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: false }); });
      (movieSwipeState.likes || []).forEach(i => { if (i && typeof i.id !== 'undefined') final[i.id] = Object.assign({}, i, { liked: true }); });
    }
    const rows = Object.values(final).sort((a, b) => {
      const likedA = a.liked ? 1 : 0;
      const likedB = b.liked ? 1 : 0;
      if (likedA !== likedB) return likedB - likedA;

      const simA = typeof a.similarity === 'number' ? a.similarity : -Infinity;
      const simB = typeof b.similarity === 'number' ? b.similarity : -Infinity;
      if (simA !== simB) return simB - simA;

      const stA = Array.isArray(a.showtimes) ? a.showtimes : [];
      const stB = Array.isArray(b.showtimes) ? b.showtimes : [];
      const minTsA = stA.reduce((acc, s) => Math.min(acc, toTimestamp(s.showdate, s.showtime)), Number.POSITIVE_INFINITY);
      const minTsB = stB.reduce((acc, s) => Math.min(acc, toTimestamp(s.showdate, s.showtime)), Number.POSITIVE_INFINITY);
      return minTsA - minTsB;
    });
    if (!rows.length) {
      movieSwipeSummary.innerHTML = '<p class="text-muted">No swipes yet.</p>';
      movieSwipeSummary.classList.remove('d-none');
      return;
    }

    const html = rows.map((m) => {
      const stList = Array.isArray(m.showtimes) ? m.showtimes : [];
      const summaryCinemas = [...new Set(stList.map(s => s.cinema).filter(Boolean))];
      const summaryDetailsLink = stList.map(s => s.details_link).find(Boolean) || '';
      const runtimeVal = m.runtime || (stList[0] && stList[0].runtime);
      const likedBadge = m.liked
        ? `<span class="me-2 cp-swipe-badge" aria-label="Liked">${SWIPE_ICON_LIKE}</span>`
        : `<span class="me-2 cp-swipe-badge" aria-label="Disliked">${SWIPE_ICON_DISLIKE}</span>`;
      const showtimeBtns2 = renderShowtimeBtns(stList);
      const timesHtml = showtimeBtns2 ? `<div class="cp-showtime-groups">${showtimeBtns2}</div>` : '';
      const reasonHtml = m.reason ? `<p class="cp-swipe-reason"><strong>Why you might like it:</strong> ${esc(m.reason)}</p>` : '';
      const synopsisContent = m.synopsis ? `<p class="cp-synopsis">${esc(m.synopsis)}</p>` : '';
      const expandableEl = reasonHtml || synopsisContent ? `${reasonHtml}${synopsisContent}` : '';
      return renderFilmBanner(
        { ...m, image_url: m.scraped_image_url || m.image_url, runtime: runtimeVal },
        {
          titleContent: `${likedBadge}${titleHtml(m.title, summaryCinemas, summaryDetailsLink)}`,
          timesHtml,
          expandableEl,
        }
      );
    }).join('');

    movieSwipeSummary.innerHTML = `<p class="cp-section-title" style="margin-bottom:1rem">Our Picks</p>${html}`;
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
      const preference = (moviePreferenceInput && moviePreferenceInput.value || '').trim();
      if (!preference) { if (movieErrEl) { movieErrEl.textContent = 'Please enter a preference.'; movieErrEl.classList.remove('d-none'); } return; }
      if (movieErrEl) movieErrEl.classList.add('d-none');
      if (movieSubmitBtn) { movieSubmitBtn.style.width = movieSubmitBtn.offsetWidth + 'px'; movieSubmitBtn.style.justifyContent = 'center'; movieSubmitBtn.disabled = true; movieSubmitBtn.innerHTML = '<span class="cp-spinner"></span>'; }
      try {
        const res = await fetch('/api/recommend_movies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preference, session_token: sessionToken }) });
        const data = await res.json();
        if (!res.ok) { const msg = (data && data.error) ? data.error : 'Request failed'; if (movieErrEl) { movieErrEl.textContent = msg; movieErrEl.classList.remove('d-none'); } return; }
        if (data && Array.isArray(data.results)) {
          currentRunId = data.run_id || null;
          renderMovieCards(data.results);
        } else {
          currentRunId = null;
          renderMovieCards(Array.isArray(data) ? data : []);
        }
        if (movieResultWrapper) movieResultWrapper.classList.remove('d-none');
        movieResultWrapper && movieResultWrapper.scrollIntoView({ behavior: 'smooth' });
      } catch (e) {
        if (movieErrEl) { movieErrEl.textContent = 'Network error. Try again.'; movieErrEl.classList.remove('d-none'); }
      } finally {
        if (movieSubmitBtn) { movieSubmitBtn.disabled = false; movieSubmitBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/></svg> Recommend'; movieSubmitBtn.style.width = ''; movieSubmitBtn.style.justifyContent = ''; }
      }
    });
  }

  if (movieClearBtn) {
    movieClearBtn.addEventListener('click', () => {
      clearMovieCards();
      if (movieResultWrapper) movieResultWrapper.classList.add('d-none');
      if (moviePreferenceInput) moviePreferenceInput.value = '';
    });
  }

  // --- Showtime search handlers ---
  function setShowtimeLoading(isLoading) {
    if (showtimeSearchButton) {
      if (isLoading) {
        showtimeSearchButton.style.width = showtimeSearchButton.offsetWidth + 'px';
        showtimeSearchButton.style.justifyContent = 'center';
        showtimeSearchButton.style.pointerEvents = 'none';
        showtimeSearchButton.innerHTML = '<span class="cp-spinner"></span>';
      } else {
        showtimeSearchButton.innerHTML = showtimeSearchBtnOrig;
        showtimeSearchButton.style.width = '';
        showtimeSearchButton.style.justifyContent = '';
        showtimeSearchButton.style.pointerEvents = '';
      }
    }
  }

  function resetShowtimeView() {
    if (!showtimeAccordion) return;
    if (showtimeEmptyState) showtimeEmptyState.classList.add('d-none');
    if (showtimeSearchError) showtimeSearchError.classList.add('d-none');
    showtimeResults = Array.isArray(initialShowtimeData) ? initialShowtimeData.slice() : [];
    showtimePage = 1;
    renderShowtimePage(1);
  }

  if (showtimeSearchForm) {
    showtimeSearchForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const query = (showtimeSearchInput && showtimeSearchInput.value || '').trim();
      if (!query) {
        showSearchInputError('Please enter a search query.');
        return;
      }
      clearSearchInputError();
      setShowtimeLoading(true);
      try {
        const res = await fetch('/api/search_showtimes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query }) });
        const data = await res.json();
        if (!res.ok) {
          showSearchInputError((data && data.error) ? data.error : 'Search failed.');
          return;
        }
        showtimeResults = Array.isArray(data) ? data : [];
        renderShowtimePage(1);
        const calView = document.getElementById('calendarView');
        const searchView = document.getElementById('searchResultsView');
        if (calView && searchView) { calView.style.display = 'none'; searchView.style.display = ''; }
      } catch (e) {
        showSearchInputError('Network error. Try again.');
      } finally {
        setShowtimeLoading(false);
      }
    });
  }

  if (showtimeSearchInput) {
    showtimeSearchInput.addEventListener('input', clearSearchInputError);
    showtimeSearchInput.addEventListener('focus', clearSearchInputError);
  }



  if (showtimePrevPage) {
    showtimePrevPage.addEventListener('click', () => {
      renderShowtimePage(showtimePage - 1);
    });
  }

  if (showtimeNextPage) {
    showtimeNextPage.addEventListener('click', () => {
      renderShowtimePage(showtimePage + 1);
    });
  }

  if (showtimePageGo) {
    showtimePageGo.addEventListener('click', () => {
      if (!showtimePageInput) return;
      const val = parseInt(showtimePageInput.value, 10);
      const target = Number.isFinite(val) ? Math.min(Math.max(1, val), showtimeTotalPages) : showtimePage;
      renderShowtimePage(target);
    });
  }

  if (showtimePageInput) {
    showtimePageInput.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        const val = parseInt(showtimePageInput.value, 10);
        const target = Number.isFinite(val) ? Math.min(Math.max(1, val), showtimeTotalPages) : showtimePage;
        renderShowtimePage(target);
      }
    });
  }

  const backToCalendar = document.getElementById('backToCalendar');
  if (backToCalendar) {
    backToCalendar.addEventListener('click', () => {
      const calView = document.getElementById('calendarView');
      const searchView = document.getElementById('searchResultsView');
      if (calView && searchView) { calView.style.display = ''; searchView.style.display = 'none'; }
      if (showtimeSearchInput) showtimeSearchInput.value = '';
      if (showtimeSearchError) showtimeSearchError.classList.add('d-none');
      if (typeof window._closeSearch === 'function') window._closeSearch();
    });
  }

  // Initial render for server-provided showtimes, paginated to 10 per page
  if (Array.isArray(initialShowtimeData) && initialShowtimeData.length > 0) {
    showtimeResults = initialShowtimeData.slice();
    renderShowtimePage(1);
  }

});
