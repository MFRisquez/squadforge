const out = document.getElementById("out");
const btn = document.getElementById("loadDemo");

btn.addEventListener("click", async () => {
  out.textContent = "Loading…";
  try {
    const res = await fetch("/api/demo-scores");
    const data = await res.json();
    const lines = Object.entries(data).map(([pos, row]) => {
      return `${pos}: ${row.total} pts\n` + JSON.stringify(row.breakdown, null, 2);
    });
    out.textContent = lines.join("\n\n");
  } catch (err) {
    out.textContent = "Could not load demo scores. Is the server running?\n" + err;
  }
});
