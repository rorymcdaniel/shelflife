/* Shelflife integration UI. No keys or credentials are embedded in this file. */
(() => {
  if (window.Shelflife) return;
  const style = document.createElement("style");
  style.textContent = `
    .shelflife-dialog { color:#edf4f1;background:#14231f;border:1px solid #426c5b;border-radius:16px;padding:28px;max-width:420px;width:calc(100% - 64px);font:16px/1.5 system-ui;box-shadow:0 20px 80px #0008; }
    .shelflife-dialog::backdrop {background:#0009}
    .shelflife-dialog h2 {margin:0 0 12px;font-size:24px}
    .shelflife-dialog label {display:block;margin-top:20px}
    .shelflife-dialog select,.shelflife-dialog input {box-sizing:border-box;width:100%;padding:12px;margin-top:6px;background:#21382f;color:white;border:1px solid #6e9d87;border-radius:8px;font:inherit}
    .shelflife-actions {display:flex;gap:12px;margin-top:24px;justify-content:flex-end}
    .shelflife-dialog button,.shelflife-keep {padding:10px 18px;border:1px solid #6e9d87;border-radius:8px;background:#21382f;color:#edf4f1;font:inherit;cursor:pointer}
    .shelflife-dialog button[type=submit] {background:#b8e6b1;color:#14231f;font-weight:650}
    .shelflife-status {display:block;padding:12px 0;color:inherit;font:14px/1.5 system-ui}
    .shelflife-fixed {position:fixed;bottom:24px;right:24px;z-index:1000;box-shadow:0 4px 20px #0006}
  `;
  document.head.append(style);
  let pending = Promise.resolve();
  function dialog({
    requesting = false,
    title = "Keep this title",
    status = "",
  } = {}) {
    const task = () =>
      new Promise((resolve, reject) => {
        const previous = document.activeElement;
        const element = document.createElement("dialog");
        element.className = "shelflife-dialog";
        const form = document.createElement("form");
        const heading = document.createElement("h2");
        heading.textContent = requesting ? "How long should it stay?" : title;
        const explanation = document.createElement("p");
        explanation.textContent = requesting
          ? "Requests stay for 60 days after they become available. TV seasons get their full window after the season is complete. Anyone can extend the deadline or keep it forever."
          : status ||
            "Your choice is accepted immediately. A longer or permanent keep already made by someone else stays in place.";
        const label = document.createElement("label");
        label.textContent = requesting ? "Keep for" : "Keep for at least";
        const select = document.createElement("select");
        select.setAttribute("aria-label", "Retention period");
        for (const [value, text] of [
          ["60", requesting ? "60 days (default)" : "60 more days"],
          ["180", "180 days"],
          ["365", "1 year"],
          ["custom", "Choose a number of days"],
          ["forever", "Keep forever"],
        ]) {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = text;
          select.append(option);
        }
        const custom = document.createElement("input");
        custom.type = "number";
        custom.min = "60";
        custom.max = "36500";
        custom.step = "1";
        custom.value = "180";
        custom.hidden = true;
        custom.setAttribute("aria-label", "Number of days");
        select.addEventListener("change", () => {
          custom.hidden = select.value !== "custom";
          custom.required = !custom.hidden;
        });
        const actions = document.createElement("div");
        actions.className = "shelflife-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "Cancel";
        const submit = document.createElement("button");
        submit.type = "submit";
        submit.textContent = requesting ? "Request with this choice" : "Keep";
        const finish = () => {
          element.close();
          element.remove();
          if (previous?.isConnected) previous.focus();
        };
        cancel.addEventListener("click", () => {
          finish();
          reject(new DOMException("Canceled", "AbortError"));
        });
        element.addEventListener("cancel", (event) => {
          event.preventDefault();
          finish();
          reject(new DOMException("Canceled", "AbortError"));
        });
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          const days =
            select.value === "forever"
              ? null
              : Number(select.value === "custom" ? custom.value : select.value);
          if (
            days !== null &&
            (!Number.isInteger(days) || days < 60 || days > 36500)
          ) {
            custom.reportValidity();
            return;
          }
          finish();
          resolve(days);
        });
        label.append(select, custom);
        actions.append(cancel, submit);
        form.append(heading, explanation, label, actions);
        element.append(form);
        document.body.append(element);
        element.showModal();
        select.focus();
      });
    const next = pending.then(task, task);
    pending = next.catch(() => {});
    return next;
  }
  async function api(path, options = {}) {
    const response = await fetch("/shelflife" + path, options);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "Unable to save your choice. Please try again.",
      );
    }
    return response.json();
  }
  window.Shelflife = { dialog, api };
})();
