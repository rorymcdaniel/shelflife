(() => {
  if (window.__shelflifeJellyfin) return;
  window.__shelflifeJellyfin = true;
  let currentId,
    busy = false;
  function itemId() {
    const hash = location.hash;
    return hash.includes("/details")
      ? new URLSearchParams(hash.split("?")[1] || "").get("id")
      : null;
  }
  async function refresh() {
    const id = itemId();
    if (id === currentId || busy) return;
    document
      .querySelectorAll("[data-shelflife]")
      .forEach((node) => node.remove());
    currentId = null;
    const token = window.ApiClient?.accessToken?.();
    if (!id || !token || !window.Shelflife) return;
    busy = true;
    try {
      const state = await window.Shelflife.api(
        "/jellyfin/" + encodeURIComponent(id),
        { headers: { "X-Emby-Token": token } },
      );
      if (itemId() !== id) return;
      const box = document.createElement("div");
      box.dataset.shelflife = "true";
      const text = document.createElement("span");
      text.className = "shelflife-status";
      const describe = (value) =>
        value.permanent
          ? "Kept permanently"
          : value.expires_at
            ? (value.enrolled ? "Scheduled for deletion on " : "Kept until ") +
              new Date(value.expires_at).toLocaleDateString()
            : "Anyone can keep this title";
      text.textContent = describe(state);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shelflife-keep";
      button.textContent = state.permanent ? "Kept permanently" : "Keep…";
      button.disabled = state.permanent;
      button.addEventListener("click", async () => {
        try {
          const days = await window.Shelflife.dialog({
            title: "Keep " + state.title,
            status: text.textContent,
          });
          button.disabled = true;
          const result = await window.Shelflife.api(
            "/jellyfin/" + encodeURIComponent(id) + "/keep",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Emby-Token": window.ApiClient.accessToken(),
                "X-Shelflife-Intent": "keep",
              },
              body: JSON.stringify({ days }),
            },
          );
          text.textContent = describe(result);
          button.textContent = result.permanent ? "Kept permanently" : "Keep…";
          button.disabled = result.permanent;
        } catch (error) {
          button.disabled = false;
          if (error.name !== "AbortError") {
            text.textContent = error.message;
            text.setAttribute("role", "alert");
          }
        }
      });
      box.append(text, button);
      const container = document.querySelector(
        ".detailPage:not(.hide) .detailButtons, .detailPage:not(.hide) .mainDetailButtons",
      );
      if (container) container.append(box);
      else {
        box.className = "shelflife-fixed";
        document.body.append(box);
      }
      currentId = id;
    } catch {
      /* Items without a supported media identity keep their normal UI. */
    } finally {
      busy = false;
    }
  }
  window.addEventListener("hashchange", refresh);
  window.setInterval(refresh, 2000);
  refresh();
})();
