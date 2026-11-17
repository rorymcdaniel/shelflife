<script lang="ts">
  import { onMount } from "svelte";
  import { auth } from "$lib/stores/auth";
  import { get_api, fetchAPI } from "$lib/api";

  type Entry = {
    id: number;
    title: string;
    kind: string;
    season_number: number;
    permanent: boolean;
    enrolled: boolean;
    expires_at: string | null;
    available_at: string | null;
    deleted_at: string | null;
    last_error: string | null;
  };
  type Settings = {
    enabled_at: string | null;
    preview: boolean;
    paused: boolean;
    timezone: string;
    seerr_public_url: string;
    jellyfin_public_url: string;
    last_checked_at: string | null;
    last_error: string | null;
  };
  let items = $state<Entry[]>([]);
  let settings = $state<Settings | null>(null);
  let error = $state("");
  let message = $state("");
  let busy = $state(false);
  let page = $state(1);
  let total = $state(0);
  let search = $state("");
  let selected = $state<Entry | null>(null);
  let days = $state("60");
  let customDays = $state(180);
  let dialog: HTMLDialogElement;
  const admin = $derived($auth.user?.role === "admin");
  const visible = $derived(
    items.filter((item) =>
      item.title.toLowerCase().includes(search.toLowerCase()),
    ),
  );
  const date = (value: string) =>
    new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  async function load() {
    error = "";
    try {
      const result = await get_api<{
        items: Entry[];
        settings: Settings;
        total: number;
      }>(`/api/retention?page=${page}`);
      items = result.items;
      settings = result.settings;
      total = result.total;
      if (!settings.enabled_at)
        settings.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (e) {
      error =
        e instanceof Error ? e.message : "Unable to load library retention.";
    }
  }
  onMount(() => {
    void load();
  });

  async function mutate(path: string, body?: unknown, method = "POST") {
    const response = await fetchAPI(path, {
      method,
      headers: { "X-Shelflife-Intent": "keep" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(
        typeof failure.detail === "string"
          ? failure.detail
          : "Unable to save. Please try again.",
      );
    }
    return response.json();
  }
  function choose(item: Entry) {
    selected = item;
    days = "60";
    dialog.showModal();
  }
  async function saveKeep(event: SubmitEvent) {
    event.preventDefault();
    if (!selected) return;
    busy = true;
    error = "";
    try {
      const duration =
        days === "forever"
          ? null
          : days === "custom"
            ? customDays
            : Number(days);
      await mutate(`/api/retention/${selected.id}/keep`, { days: duration });
      message =
        duration === null
          ? `${selected.title} is kept permanently.`
          : `${selected.title} will stay for at least ${duration} more days.`;
      dialog.close();
      selected = null;
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : "Unable to save this keep.";
    } finally {
      busy = false;
    }
  }
  async function saveSettings(event: SubmitEvent) {
    event.preventDefault();
    if (!settings) return;
    busy = true;
    error = "";
    try {
      await mutate(
        "/api/retention/settings",
        {
          enable: true,
          paused: settings.paused,
          preview: settings.preview,
          timezone: settings.timezone,
          seerr_public_url: settings.seerr_public_url,
          jellyfin_public_url: settings.jellyfin_public_url,
        },
        "PUT",
      );
      message = "Retention settings saved.";
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : "Unable to save settings.";
    } finally {
      busy = false;
    }
  }
  async function sync() {
    busy = true;
    error = "";
    try {
      await mutate("/api/retention/sync");
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : "Unable to check the library.";
    } finally {
      busy = false;
    }
  }
</script>

<div class="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-8">
  <header class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm font-semibold uppercase tracking-widest text-primary">
        Shelflife
      </p>
      {#if settings}<span
          class="rounded-full border border-border px-3 py-1 text-sm"
          >{!settings.enabled_at
            ? "Ready to set up"
            : settings.preview
              ? "Preview · deletion off"
              : settings.paused
                ? "Cleanup paused"
                : "Automatic cleanup on"}</span
        >{/if}
    </div>
    <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">
      Make room. Keep what matters.
    </h1>
    <p class="max-w-2xl text-lg text-muted-foreground">
      New requests stay for 60 days after they become available. Anyone can give
      a title more time or keep it forever.
    </p>
    <p class="text-sm text-muted-foreground">
      On Roku, mark a title as Favorite to keep it permanently. Removing the
      favorite later leaves the keep intact.
    </p>
  </header>

  {#if error}<p
      role="alert"
      class="rounded-lg border border-red-500/40 bg-red-500/10 p-4"
    >
      {error}
    </p>{/if}
  {#if message}<p
      role="status"
      class="rounded-lg border border-primary/30 bg-primary/10 p-4"
    >
      {message}
    </p>{/if}
  {#if settings?.last_error}<p
      role="status"
      class="rounded-lg border border-amber-500/40 p-4"
    >
      Cleanup is deferred while a connection needs attention. {settings.last_error}
    </p>{/if}

  <section aria-label="Library retention" class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h2 class="text-xl font-semibold">Your shared library</h2>
        <p class="text-sm text-muted-foreground">
          Every keep takes effect automatically.
        </p>
      </div>
      <label class="text-sm"
        >Find a title<input
          type="search"
          bind:value={search}
          placeholder="Search this page"
          class="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 sm:w-64"
        /></label
      >
    </div>
    {#if !items.length}
      <div
        class="rounded-xl border border-dashed border-border p-10 text-center"
      >
        <p class="text-lg font-medium">A fresh start for new requests</p>
        <p class="mt-2 text-muted-foreground">
          New requests will appear here after setup and the first library check.
          Your existing library is not enrolled automatically.
        </p>
      </div>
    {:else}
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {#each visible as item (item.id)}
          <article
            class="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
          >
            <div>
              <p
                class="mb-2 text-xs uppercase tracking-wider text-muted-foreground"
              >
                {item.kind === "movie"
                  ? "Movie"
                  : item.season_number < 0
                    ? "Show"
                    : "Season"}
              </p>
              <h3 class="text-xl font-semibold">{item.title}</h3>
            </div>
            <div class="flex-1">
              {#if item.deleted_at}<p class="text-muted-foreground">
                  Left the library {date(item.deleted_at)}
                </p>
              {:else if item.permanent}<p class="font-medium text-primary">
                  Kept permanently
                </p>
                <p class="mt-1 text-sm text-muted-foreground">
                  This title has a home here.
                </p>
              {:else if item.expires_at}<p>
                  {item.enrolled ? "Scheduled for deletion" : "Kept until"}
                  <strong>{date(item.expires_at)}</strong>
                </p>
              {:else}<p class="text-muted-foreground">
                  Waiting for {item.kind === "movie"
                    ? "the movie"
                    : "the complete season"} to become available.
                </p>{/if}
              {#if item.last_error}<p
                  class="mt-2 text-sm text-amber-600 dark:text-amber-300"
                >
                  Cleanup deferred
                </p>{/if}
            </div>
            {#if !item.deleted_at && !item.permanent}<button
                onclick={() => choose(item)}
                class="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground hover:opacity-90"
                >Keep…</button
              >{/if}
          </article>
        {/each}
      </div>
      {#if total > 100}<nav
          aria-label="Retention pages"
          class="flex justify-between"
        >
          <button
            disabled={page === 1}
            onclick={() => {
              page--;
              void load();
            }}>Previous</button
          ><span>Page {page} of {Math.ceil(total / 100)}</span><button
            disabled={page * 100 >= total}
            onclick={() => {
              page++;
              void load();
            }}>Next</button
          >
        </nav>{/if}
    {/if}
  </section>

  {#if admin && settings}
    <details class="rounded-xl border border-border p-5">
      <summary class="cursor-pointer font-medium"
        >Manage library retention</summary
      >
      <form onsubmit={saveSettings} class="mt-5 grid gap-5 sm:grid-cols-2">
        <p class="text-sm text-muted-foreground sm:col-span-2">
          Connect Jellyfin, Seerr, Sonarr and Radarr in <a
            href="#/settings"
            class="underline">Settings</a
          > first. Enabling starts with new requests only. Turning off preview gives
          available titles a fresh full viewing window.
        </p>
        <label
          >Seerr address<input
            type="url"
            required
            bind:value={settings.seerr_public_url}
            placeholder="https://requests.example.com"
            class="mt-1 block w-full rounded-lg border border-border bg-background p-2"
          /></label
        >
        <label
          >Jellyfin address<input
            type="url"
            required
            bind:value={settings.jellyfin_public_url}
            placeholder="https://watch.example.com"
            class="mt-1 block w-full rounded-lg border border-border bg-background p-2"
          /></label
        >
        <label
          >Time zone<input
            required
            bind:value={settings.timezone}
            class="mt-1 block w-full rounded-lg border border-border bg-background p-2"
          /></label
        >
        <div class="space-y-3">
          <label class="flex items-center gap-3"
            ><input type="checkbox" bind:checked={settings.preview} /> Preview only
            — leave files and descriptions unchanged</label
          ><label class="flex items-center gap-3"
            ><input type="checkbox" bind:checked={settings.paused} /> Pause cleanup</label
          >
        </div>
        <div class="flex flex-wrap gap-3 sm:col-span-2">
          <button
            type="submit"
            disabled={busy}
            class="rounded-lg bg-primary px-4 py-2 text-primary-foreground"
            >{settings.enabled_at ? "Save settings" : "Enable preview"}</button
          ><button
            type="button"
            disabled={busy || !settings.enabled_at}
            onclick={sync}
            class="rounded-lg border border-border px-4 py-2"
            >{busy ? "Working…" : "Check library now"}</button
          >
        </div>
        {#if settings.last_checked_at}<p class="text-sm text-muted-foreground">
            Last checked {new Date(settings.last_checked_at).toLocaleString()}
          </p>{/if}
      </form>
    </details>
  {/if}
</div>

<dialog
  bind:this={dialog}
  class="w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-background p-6 text-foreground shadow-xl backdrop:bg-black/60"
>
  <form onsubmit={saveKeep} class="space-y-5">
    <h2 class="text-2xl font-semibold">Keep {selected?.title}</h2>
    <p class="text-muted-foreground">
      Your choice takes effect immediately. Everyone can keep watching.
    </p>
    <label class="block"
      >Keep for at least<select
        bind:value={days}
        class="mt-2 w-full rounded-lg border border-border bg-background p-3"
        ><option value="60">60 more days</option><option value="180"
          >180 days</option
        ><option value="365">1 year</option><option value="custom"
          >Choose a number of days</option
        ><option value="forever">Keep forever</option></select
      ></label
    >
    {#if days === "custom"}<label class="block"
        >Number of days<input
          type="number"
          min="60"
          max="36500"
          step="1"
          required
          bind:value={customDays}
          class="mt-2 w-full rounded-lg border border-border bg-background p-3"
        /></label
      >{/if}
    {#if error}<p role="alert">{error}</p>{/if}
    <div class="flex justify-end gap-3">
      <button
        type="button"
        disabled={busy}
        onclick={() => dialog.close()}
        class="rounded-lg border border-border px-4 py-2">Cancel</button
      ><button
        disabled={busy}
        type="submit"
        class="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground"
        >{busy ? "Saving…" : "Keep"}</button
      >
    </div>
  </form>
</dialog>
