document.addEventListener("DOMContentLoaded", () => {
  const nav = document.querySelector(".navbar-nav.me-auto");
  if (!nav || document.getElementById("pwnmychall-nav-link")) {
    return;
  }
  if (!window.init || !window.init.userId) {
    return;
  }

  let base = "";
  if (window.init && typeof window.init.urlRoot === "string") {
    base = window.init.urlRoot;
  }
  if (base === "/") {
    base = "";
  }

  const li = document.createElement("li");
  li.className = "nav-item";
  li.id = "pwnmychall-nav-link";

  const link = document.createElement("a");
  link.className = "nav-link";
  link.href = `${base}/pwnmychall/dashboard`;
  link.textContent = "PwnMyChall";

  li.appendChild(link);
  nav.appendChild(li);
});
