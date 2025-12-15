document.addEventListener('DOMContentLoaded', function () {
  const openBtn = document.getElementById('openRecommendBtn'); // may be unused now
  const form = document.getElementById('recommendForm');
  const errEl = document.getElementById('recommendError');
  const resultWrapper = document.getElementById('recommendResultWrapper');
  const resultEl = document.getElementById('recommendResult');
  const clearBtn = document.getElementById('clearRecommend');
  const submitBtn = document.getElementById('submitRecommend');

  if (openBtn) {
    openBtn.addEventListener('click', () => {
      // if present, focus first field
      document.getElementById('likedMovies').focus();
    });
  }

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const liked = document.getElementById('likedMovies').value.trim();
    const mood = document.getElementById('mood').value.trim();

    if (!liked && !mood) {
      errEl.textContent = 'Please enter something you liked or a mood.';
      errEl.classList.remove('d-none');
      return;
    }
    errEl.classList.add('d-none');

    submitBtn.disabled = true;
    const origText = submitBtn.textContent;
    submitBtn.textContent = 'Thinking...';

    try {
      const res = await fetch('/api/recommend', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ liked_movies: liked, mood: mood })
      });

      const text = await res.text();
      if (!res.ok) {
        resultEl.textContent = `Error: ${text}`;
      } else {
        resultEl.textContent = text;
      }
      resultWrapper.classList.remove('d-none');
      resultWrapper.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      errEl.textContent = 'Network error. Try again.';
      errEl.classList.remove('d-none');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = origText;
    }
  });

  clearBtn?.addEventListener('click', () => {
    resultEl.textContent = '';
    resultWrapper.classList.add('d-none');
    document.getElementById('likedMovies').value = '';
    document.getElementById('mood').value = '';
    errEl.classList.add('d-none');
  });
});
