(() => {
  const message = document.querySelector("#dashboard-message");
  const buttons = [...document.querySelectorAll("button")];

  function setBusy(busy) {
    buttons.forEach((button) => { button.disabled = busy; });
    const classify = document.querySelector("#classify-now");
    if (classify) classify.textContent = busy ? "Working…" : "Classify now";
  }

  function showMessage(text, error = false) {
    if (!message) return;
    message.textContent = text;
    message.hidden = false;
    message.classList.toggle("error", error);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "content-type": "application/json", ...(options.headers || {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || "Request failed");
    return body;
  }

  document.querySelectorAll("[data-date]").forEach((element) => {
    const value = element.dataset.date;
    if (!value) return;
    const date = new Date(value);
    if (!Number.isNaN(date.valueOf())) {
      element.textContent = new Intl.DateTimeFormat(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      }).format(date);
    }
  });

  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
      let visible = 0;
      document.querySelectorAll(".decision-row").forEach((row) => {
        const show = filter === "all" || row.dataset.status === filter;
        row.hidden = !show;
        if (show) visible += 1;
      });
      const titles = { all: "Recent decisions", review: "Needs review", error: "Processing errors" };
      document.querySelector("#panel-title").textContent = titles[filter];
      document.querySelector("#empty-state").hidden = visible !== 0;
    });
  });

  document.querySelector("#classify-now")?.addEventListener("click", async () => {
    setBusy(true);
    if (message) message.hidden = true;
    try {
      const result = await api("/api/classify", { method: "POST", body: "{}" });
      showMessage(`Processed ${result.processed}: ${result.labeled} labeled, ${result.review} for review, ${result.failed} failed.`);
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      showMessage(error.message || "Classification failed", true);
      setBusy(false);
    }
  });

  document.querySelector("#learning-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBusy(true);
    if (message) message.hidden = true;
    const resultPanel = document.querySelector("#learning-result");
    try {
      const result = await api("/api/learn/classify", {
        method: "POST",
        body: JSON.stringify({
          sender: document.querySelector("#learning-sender").value,
          subject: document.querySelector("#learning-subject").value,
          message: document.querySelector("#learning-message").value,
        }),
      });
      const category = result.judgments.category;
      document.querySelector("#learning-category").textContent = category.selected.replaceAll("_", " ");
      document.querySelector("#learning-confidence").textContent = `${Math.round(category.confidence * 100)}% category confidence`;
      document.querySelector("#learning-action").textContent = `${Math.round(result.judgments.requires_action.yes_probability * 100)}% yes`;
      document.querySelector("#learning-urgency").textContent = `${result.judgments.urgency.score.toFixed(1)} / 2`;
      document.querySelector("#learning-route").textContent = result.policy.route.replaceAll("_", " ");
      document.querySelector("#learning-reason").textContent = result.policy.reason;

      const probabilities = document.querySelector("#learning-probabilities");
      probabilities.replaceChildren();
      Object.entries(category.probabilities)
        .sort((left, right) => right[1] - left[1])
        .forEach(([name, probability]) => {
          const row = document.createElement("div");
          const label = document.createElement("span");
          const meter = document.createElement("i");
          const value = document.createElement("b");
          label.textContent = name.replaceAll("_", " ");
          meter.style.setProperty("--probability", `${probability * 100}%`);
          value.textContent = `${Math.round(probability * 100)}%`;
          row.append(label, meter, value);
          probabilities.append(row);
        });
      resultPanel.hidden = false;
    } catch (error) {
      showMessage(error.message || "Could not evaluate the learning sample", true);
      if (resultPanel) resultPanel.hidden = true;
    } finally {
      setBusy(false);
    }
  });

  document.querySelectorAll(".apply-review").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.id;
      const category = document.querySelector(`#category-${id}`).value;
      setBusy(true);
      try {
        await api(`/api/classifications/${id}`, {
          method: "PATCH", body: JSON.stringify({ category }),
        });
        window.location.reload();
      } catch (error) {
        showMessage(error.message || "Could not update the label", true);
        setBusy(false);
      }
    });
  });

  document.querySelector("#disconnect")?.addEventListener("click", async () => {
    if (!window.confirm("Disconnect Gmail and remove locally stored classification history?")) return;
    setBusy(true);
    try {
      await api("/api/auth/disconnect", { method: "POST", body: "{}" });
      window.location.assign("/");
    } catch (error) {
      showMessage(error.message || "Could not disconnect Gmail", true);
      setBusy(false);
    }
  });
})();
