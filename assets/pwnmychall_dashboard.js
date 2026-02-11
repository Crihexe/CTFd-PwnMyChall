function pwnmychallApiFetch(path, options = {}) {
  if (window.CTFd && typeof window.CTFd.fetch === "function") {
    return window.CTFd.fetch(path, options);
  }
  let urlRoot = window.init && window.init.urlRoot ? window.init.urlRoot : "";
  if (urlRoot === "/") {
    urlRoot = "";
  }
  const opts = {
    credentials: "same-origin",
    ...options,
    headers: options.headers || {},
  };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.headers["CSRF-Token"] = window.init ? window.init.csrfNonce : "";
  }
  return fetch(`${urlRoot}${path}`, opts);
}

function renderStateBadge(state) {
  const badgeClass = state === "hidden" ? "bg-danger" : "bg-success";
  return `<span class="badge ${badgeClass}">${state}</span>`;
}

function getUrlRoot() {
  const root = window.init && typeof window.init.urlRoot === "string" ? window.init.urlRoot : "";
  return root === "/" ? "" : root;
}

function renderRow(challenge) {
  const urlRoot = getUrlRoot();
  const editUrl = `${urlRoot}/pwnmychall/challenges/${challenge.id}/edit`;
  return `
    <tr data-challenge-id="${challenge.id}">
      <td>${challenge.name}</td>
      <td>${challenge.category}</td>
      <td class="text-center">${renderStateBadge(challenge.state)}</td>
      <td class="text-center">${challenge.solves ?? 0}</td>
      <td class="text-center">${challenge.reward ?? "-"}</td>
      <td class="text-center">
        <a class="btn btn-sm btn-outline-secondary" href="${editUrl}">Modifica</a>
        <button class="btn btn-sm btn-outline-danger pmc-delete" type="button">Elimina</button>
      </td>
    </tr>
  `;
}

document.addEventListener("DOMContentLoaded", () => {
  const loading = document.getElementById("pwnmychall-loading");
  const errorBox = document.getElementById("pwnmychall-error");
  const empty = document.getElementById("pwnmychall-empty");
  const tbody = document.getElementById("pwnmychall-list-body");

  function setError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("d-none");
  }

  function clearError() {
    errorBox.classList.add("d-none");
    errorBox.textContent = "";
  }

  function loadChallenges() {
    clearError();
    loading.classList.remove("d-none");
    pwnmychallApiFetch("/api/v1/pwnmychall/challenges", { method: "GET" })
      .then((response) => response.json())
      .then((data) => {
        loading.classList.add("d-none");
        if (!data.success) {
          setError("Errore nel caricamento delle challenge.");
          return;
        }

        tbody.innerHTML = "";
        if (!data.data.length) {
          empty.classList.remove("d-none");
          return;
        }
        empty.classList.add("d-none");
        data.data.forEach((challenge) => {
          tbody.insertAdjacentHTML("beforeend", renderRow(challenge));
        });
      })
      .catch(() => {
        loading.classList.add("d-none");
        setError("Errore di rete nel caricamento.");
      });
  }

  tbody.addEventListener("click", (event) => {
    if (!event.target.classList.contains("pmc-delete")) {
      return;
    }
    const row = event.target.closest("tr");
    const challengeId = row.getAttribute("data-challenge-id");
    if (!confirm("Vuoi eliminare questa challenge?")) {
      return;
    }
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}`, {
      method: "DELETE",
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          row.remove();
          if (!tbody.children.length) {
            empty.classList.remove("d-none");
          }
        } else {
          setError("Non è stato possibile eliminare la challenge.");
        }
      })
      .catch(() => {
        setError("Errore di rete durante l'eliminazione.");
      });
  });

  loadChallenges();
});
