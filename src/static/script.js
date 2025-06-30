async function getRecommendations() {
    try {
        const response = await fetch('/recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: "Recommend 5 movies" })
        });

        const data = await response.json();
        const list = document.getElementById("recommendationsList");
        list.innerHTML = "";

        data.recommendations.forEach(movie => {
            let li = document.createElement("li");
            li.textContent = movie;
            list.appendChild(li);
        });

        // Show Bootstrap modal
        var modal = new bootstrap.Modal(document.getElementById('recommendDialog'));
        modal.show();

    } catch (error) {
        console.error("Error fetching recommendations:", error);
    }
}