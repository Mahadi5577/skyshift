// SkyShift entry point: tabs, Candidates board, startup.
import { api } from "./api.js";
import { initExplore, openFromHash, setTarget } from "./explore.js";
import { initHunt } from "./hunt.js";

const $ = (s) => document.querySelector(s);

function showTab(name) {
  document.querySelectorAll(".tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== `tab-${name}`));
  if (name === "board") loadBoard();
}

async function loadBoard() {
  const body = $("#board-body");
  let data;
  try {
    data = await api.board();
  } catch (e) {
    body.innerHTML = `<tr><td colspan="6" class="muted">Could not load: ${e.message}</td></tr>`;
    return;
  }
  if (!data.candidates.length) {
    body.innerHTML = '<tr><td colspan="6" class="muted">No flags yet. Play real rounds in Hunt to add some.</td></tr>';
    return;
  }
  body.innerHTML = "";
  data.candidates.forEach((c, k) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${k + 1}</td><td>${c.ra.toFixed(4)}°, ${c.dec.toFixed(4)}°</td><td>${c.votes}</td>
      <td>${c.score.toFixed(2)}</td><td></td><td><button class="btn small">Open</button></td>`;
    tr.children[4].textContent = c.known || "no match: unexplained";
    tr.querySelector("button").onclick = () => {
      showTab("explore");
      setTarget({ name: `Candidate #${k + 1}`, ra: c.ra, dec: c.dec }, { zoom: c.zoom });
    };
    body.append(tr);
  });
}

document.querySelectorAll(".tabs [data-tab]").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
$("#board-refresh").onclick = loadBoard;

initHunt();
initExplore().then((stops) => {
  if (!openFromHash(stops) && stops.length) {
    setTarget({ name: stops[0].title, ra: stops[0].ra, dec: stops[0].dec }, { stop: stops[0] });
  }
  // Shared links opened in an already-open tab only change the hash.
  window.addEventListener("hashchange", () => {
    showTab("explore");
    openFromHash(stops);
  });
});
