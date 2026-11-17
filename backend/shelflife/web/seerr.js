/* Ask before Seerr submits a new request, preserving its own auth and validation. */
(() => {
  if (window.__shelflifeSeerr) return;
  window.__shelflifeSeerr = true;
  const isRequest = (method, url) => {
    try {
      const parsed = new URL(url, location.href);
      return (
        String(method).toUpperCase() === "POST" &&
        parsed.origin === location.origin &&
        parsed.pathname === "/api/v1/request"
      );
    } catch {
      return false;
    }
  };
  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const req = new Request(input, init);
    if (!isRequest(req.method, req.url))
      return originalFetch.call(this, input, init);
    const body = await req.clone().json();
    body.shelflifeDays = await window.Shelflife.dialog({ requesting: true });
    const headers = new Headers(req.headers);
    headers.set("X-Shelflife-Intent", "keep");
    headers.set("Content-Type", "application/json");
    return originalFetch.call(
      this,
      new Request(req, { headers, body: JSON.stringify(body) }),
    );
  };
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  const requests = new WeakMap();
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    requests.set(this, isRequest(method, url));
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (body) {
    if (!requests.get(this)) return send.call(this, body);
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch {
      return send.call(this, body);
    }
    window.Shelflife.dialog({ requesting: true })
      .then((days) => {
        parsed.shelflifeDays = days;
        this.setRequestHeader("X-Shelflife-Intent", "keep");
        send.call(this, JSON.stringify(parsed));
      })
      .catch(() => {
        this.abort();
        this.dispatchEvent(new ProgressEvent("abort"));
      });
  };
})();
