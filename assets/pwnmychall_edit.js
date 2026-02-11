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

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("pwnmychall-edit-form");
  const errorBox = document.getElementById("pwnmychall-edit-errors");
  const challengeId = parseInt(form.dataset.challengeId, 10);

  const flagsBody = document.getElementById("pwnmychall-flags-body");
  const flagsError = document.getElementById("pwnmychall-flags-error");
  const flagForm = document.getElementById("pwnmychall-flag-form");
  const flagIdInput = document.getElementById("pmc-flag-id");
  const flagTypeSelect = document.getElementById("pmc-flag-type");
  const flagContentInput = document.getElementById("pmc-flag-content");
  const flagDataSelect = document.getElementById("pmc-flag-data");
  const flagCancelBtn = document.getElementById("pmc-flag-cancel");

  const tagsContainer = document.getElementById("pwnmychall-tags");
  const tagInput = document.getElementById("pwnmychall-tag-input");
  const tagsError = document.getElementById("pwnmychall-tags-error");

  const filesBody = document.getElementById("pwnmychall-files-body");
  const filesError = document.getElementById("pwnmychall-files-error");
  const fileForm = document.getElementById("pwnmychall-file-form");
  const fileInput = document.getElementById("pmc-file");
  const fileLocationInput = document.getElementById("pmc-file-location");

  function showError(box, message) {
    box.textContent = message;
    box.classList.remove("d-none");
  }

  function clearError(box) {
    box.classList.add("d-none");
    box.textContent = "";
  }

  function setFormValues(data) {
    document.getElementById("pmc-name").value = data.name || "";
    document.getElementById("pmc-category").value = data.category || "";
    document.getElementById("pmc-state").value = data.state || "hidden";
    document.getElementById("pmc-description").value = data.description || "";
    document.getElementById("pmc-initial").value = data.initial ?? "";
    document.getElementById("pmc-minimum").value = data.minimum ?? "";
  }

  function loadChallenge() {
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}`, {
      method: "GET",
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(errorBox, "Errore nel caricamento della challenge.");
          return;
        }
        setFormValues(data.data);
      })
      .catch(() => {
        showError(errorBox, "Errore di rete nel caricamento.");
      });
  }

  function submitUpdate(payload) {
    clearError(errorBox);
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}`, {
      method: "PATCH",
      headers: { Accept: "application/json" },
      body: JSON.stringify(payload),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(errorBox, "Errore nel salvataggio.");
        }
      })
      .catch(() => {
        showError(errorBox, "Errore di rete nel salvataggio.");
      });
  }

  function resetFlagForm() {
    flagIdInput.value = "";
    flagContentInput.value = "";
    flagDataSelect.value = "";
  }

  function renderFlagRow(flag) {
    return `
      <tr data-flag-id="${flag.id}" data-flag-type="${flag.type}" data-flag-content="${escapeHtml(
        flag.content,
      )}" data-flag-data="${escapeHtml(flag.data)}">
        <td class="text-center">${flag.type}</td>
        <td><pre class="mb-0">${escapeHtml(flag.content)}</pre></td>
        <td class="text-center">
          <button class="btn btn-sm btn-outline-secondary pmc-flag-edit" type="button">Modifica</button>
          <button class="btn btn-sm btn-outline-danger pmc-flag-delete" type="button">Elimina</button>
        </td>
      </tr>
    `;
  }

  function loadFlags() {
    clearError(flagsError);
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}/flags`, {
      method: "GET",
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(flagsError, "Errore nel caricamento delle flags.");
          return;
        }
        flagsBody.innerHTML = "";
        data.data.forEach((flag) => {
          flagsBody.insertAdjacentHTML("beforeend", renderFlagRow(flag));
        });
      })
      .catch(() => {
        showError(flagsError, "Errore di rete nelle flags.");
      });
  }

  function loadFlagTypes() {
    pwnmychallApiFetch("/api/v1/pwnmychall/flags/types", { method: "GET" })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          return;
        }
        flagTypeSelect.innerHTML = "";
        Object.keys(data.data).forEach((type) => {
          const opt = document.createElement("option");
          opt.value = type;
          opt.textContent = type;
          flagTypeSelect.appendChild(opt);
        });
      })
      .catch(() => {});
  }

  function renderTagBadge(tag) {
    return `
      <span class="badge bg-primary mx-1 challenge-tag" data-tag-id="${tag.id}">
        <span>${escapeHtml(tag.value)}</span>
        <a class="btn-fa delete-tag">&times;</a>
      </span>
    `;
  }

  function loadTags() {
    clearError(tagsError);
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}/tags`, {
      method: "GET",
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(tagsError, "Errore nel caricamento dei tag.");
          return;
        }
        tagsContainer.innerHTML = "";
        data.data.forEach((tag) => {
          tagsContainer.insertAdjacentHTML("beforeend", renderTagBadge(tag));
        });
      })
      .catch(() => {
        showError(tagsError, "Errore di rete nei tag.");
      });
  }

  function renderFileRow(file) {
    let urlRoot = window.init && window.init.urlRoot ? window.init.urlRoot : "";
    if (urlRoot === "/") {
      urlRoot = "";
    }
    const fileUrl = `${urlRoot}/files/${file.location}`;
    return `
      <tr data-file-id="${file.id}">
        <td><a href="${fileUrl}" target="_blank">${escapeHtml(file.location)}</a></td>
        <td class="text-center"><code>${escapeHtml(file.sha1sum)}</code></td>
        <td class="text-center">
          <button class="btn btn-sm btn-outline-danger pmc-file-delete" type="button">Elimina</button>
        </td>
      </tr>
    `;
  }

  function loadFiles() {
    clearError(filesError);
    pwnmychallApiFetch(`/api/v1/pwnmychall/challenges/${challengeId}/files`, {
      method: "GET",
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(filesError, "Errore nel caricamento dei file.");
          return;
        }
        filesBody.innerHTML = "";
        data.data.forEach((file) => {
          filesBody.insertAdjacentHTML("beforeend", renderFileRow(file));
        });
      })
      .catch(() => {
        showError(filesError, "Errore di rete nei file.");
      });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const payload = {
      name: document.getElementById("pmc-name").value.trim(),
      category: document.getElementById("pmc-category").value.trim(),
      state: document.getElementById("pmc-state").value,
      description: document.getElementById("pmc-description").value,
      initial: document.getElementById("pmc-initial").value,
      minimum: document.getElementById("pmc-minimum").value,
    };
    submitUpdate(payload);
  });

  flagsBody.addEventListener("click", (event) => {
    if (event.target.classList.contains("pmc-flag-edit")) {
      const row = event.target.closest("tr");
      flagIdInput.value = row.dataset.flagId;
      flagTypeSelect.value = row.dataset.flagType;
      flagContentInput.value = row.dataset.flagContent;
      flagDataSelect.value = row.dataset.flagData;
    }
    if (event.target.classList.contains("pmc-flag-delete")) {
      const row = event.target.closest("tr");
      const flagId = row.dataset.flagId;
      if (!confirm("Eliminare questa flag?")) {
        return;
      }
      pwnmychallApiFetch(`/api/v1/pwnmychall/flags/${flagId}`, { method: "DELETE" })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            row.remove();
          } else {
            showError(flagsError, "Impossibile eliminare la flag.");
          }
        })
        .catch(() => showError(flagsError, "Errore di rete nella flag."));
    }
  });

  flagForm.addEventListener("submit", (event) => {
    event.preventDefault();
    clearError(flagsError);
    const payload = {
      challenge: challengeId,
      type: flagTypeSelect.value,
      content: flagContentInput.value.trim(),
      data: flagDataSelect.value,
    };

    const flagId = flagIdInput.value;
    const url = flagId
      ? `/api/v1/pwnmychall/flags/${flagId}`
      : "/api/v1/pwnmychall/flags";
    const method = flagId ? "PATCH" : "POST";

    pwnmychallApiFetch(url, {
      method,
      headers: { Accept: "application/json" },
      body: JSON.stringify(payload),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(flagsError, "Errore nel salvataggio della flag.");
          return;
        }
        resetFlagForm();
        loadFlags();
      })
      .catch(() => {
        showError(flagsError, "Errore di rete nel salvataggio della flag.");
      });
  });

  flagCancelBtn.addEventListener("click", () => {
    resetFlagForm();
  });

  tagsContainer.addEventListener("click", (event) => {
    const badge = event.target.closest("[data-tag-id]");
    if (!badge || !event.target.classList.contains("delete-tag")) {
      return;
    }
    const tagId = badge.dataset.tagId;
    pwnmychallApiFetch(`/api/v1/pwnmychall/tags/${tagId}`, {
      method: "DELETE",
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          badge.remove();
        } else {
          showError(tagsError, "Impossibile eliminare il tag.");
        }
      })
      .catch(() => {
        showError(tagsError, "Errore di rete nel tag.");
      });
  });

  tagInput.addEventListener("keyup", (event) => {
    if (event.key !== "Enter") {
      return;
    }
    const value = tagInput.value.trim();
    if (!value) {
      return;
    }
    clearError(tagsError);
    pwnmychallApiFetch("/api/v1/pwnmychall/tags", {
      method: "POST",
      headers: { Accept: "application/json" },
      body: JSON.stringify({ value, challenge: challengeId }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(tagsError, "Errore nel salvataggio del tag.");
          return;
        }
        tagInput.value = "";
        loadTags();
      })
      .catch(() => {
        showError(tagsError, "Errore di rete nel tag.");
      });
  });

  filesBody.addEventListener("click", (event) => {
    if (!event.target.classList.contains("pmc-file-delete")) {
      return;
    }
    const row = event.target.closest("tr");
    const fileId = row.dataset.fileId;
    if (!confirm("Eliminare questo file?")) {
      return;
    }
    pwnmychallApiFetch(`/api/v1/pwnmychall/files/${fileId}`, {
      method: "DELETE",
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          row.remove();
        } else {
          showError(filesError, "Impossibile eliminare il file.");
        }
      })
      .catch(() => showError(filesError, "Errore di rete nel file."));
  });

  fileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    clearError(filesError);
    if (!fileInput.files.length) {
      showError(filesError, "Seleziona un file.");
      return;
    }
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("nonce", window.init ? window.init.csrfNonce : "");
    if (fileLocationInput.value.trim()) {
      formData.append("location", fileLocationInput.value.trim());
    }

    let urlRoot = window.init && window.init.urlRoot ? window.init.urlRoot : "";
    if (urlRoot === "/") {
      urlRoot = "";
    }
    fetch(`${urlRoot}/api/v1/pwnmychall/challenges/${challengeId}/files`, {
      method: "POST",
      credentials: "same-origin",
      body: formData,
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showError(filesError, "Errore nel caricamento del file.");
          return;
        }
        fileForm.reset();
        loadFiles();
      })
      .catch(() => {
        showError(filesError, "Errore di rete nel caricamento del file.");
      });
  });

  loadChallenge();
  loadFlagTypes();
  loadFlags();
  loadTags();
  loadFiles();
});
