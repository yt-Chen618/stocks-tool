(function () {
  const state = {
    initialized: false,
    watchlists: [],
    editorMode: "edit",
    refreshGeneration: 0,
  };
  const els = {};

  function bindElements() {
    els.select = document.getElementById("research-watchlist-select");
    els.manageButton = document.getElementById("manage-watchlist-button");
    els.dialog = document.getElementById("watchlist-dialog");
    els.closeButton = document.getElementById("close-watchlist-dialog");
    els.form = document.getElementById("watchlist-form");
    els.name = document.getElementById("watchlist-name");
    els.description = document.getElementById("watchlist-description");
    els.isDefault = document.getElementById("watchlist-default");
    els.saveButton = document.getElementById("watchlist-save");
    els.itemForm = document.getElementById("watchlist-item-form");
    els.symbol = document.getElementById("watchlist-symbol");
    els.assetType = document.getElementById("watchlist-asset-type");
    els.notes = document.getElementById("watchlist-notes");
    els.addItemButton = document.getElementById("watchlist-add-item");
    els.itemsBody = document.getElementById("watchlist-items-body");
    els.status = document.getElementById("research-status");
  }

  function isChinese() {
    return document.documentElement.lang.toLowerCase().startsWith("zh");
  }

  function copy(zh, en) {
    return isChinese() ? zh : en;
  }

  function setStatus(message, tone = "") {
    if (!els.status) {
      return;
    }
    els.status.textContent = message;
    els.status.classList.remove("success", "warning", "error");
    if (tone) {
      els.status.classList.add(tone);
    }
  }

  function apiFetch(url, options) {
    const fetchJson = window.StocksToolApiClient?.fetchJson || window.fetchJson;
    if (typeof fetchJson !== "function") {
      throw new Error("Stocks Tool API client is unavailable.");
    }
    return fetchJson(url, options);
  }

  function selectedWatchlist() {
    const selectedId = getSelectedId();
    return state.watchlists.find((watchlist) => watchlist.id === selectedId) || null;
  }

  function getSelectedId() {
    return els.select?.value || "";
  }

  function chooseSelectedId(preferredId = "") {
    if (state.watchlists.some((watchlist) => watchlist.id === preferredId)) {
      return preferredId;
    }
    return state.watchlists.find((watchlist) => watchlist.is_default)?.id || state.watchlists[0]?.id || "";
  }

  function renderSelect(preferredId = "") {
    if (!els.select) {
      return;
    }
    const selectedId = chooseSelectedId(preferredId);
    els.select.replaceChildren();
    if (state.watchlists.length === 0) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = copy("暂无自选列表", "No watchlists");
      els.select.append(emptyOption);
    } else {
      for (const watchlist of state.watchlists) {
        const option = document.createElement("option");
        option.value = watchlist.id;
        option.textContent = watchlist.is_default
          ? `${watchlist.name} ${copy("（默认）", "(Default)")}`
          : watchlist.name;
        els.select.append(option);
      }
    }
    els.select.value = selectedId;
  }

  function createTextCell(value) {
    const cell = document.createElement("td");
    cell.textContent = value || "--";
    return cell;
  }

  function createItemActions(item) {
    const cell = document.createElement("td");
    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "table-action";
    saveButton.dataset.watchlistAction = "save-notes";
    saveButton.dataset.itemId = item.id;
    saveButton.textContent = copy("保存备注", "Save Notes");

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "table-action";
    removeButton.dataset.watchlistAction = "remove-item";
    removeButton.dataset.itemId = item.id;
    removeButton.textContent = copy("移除", "Remove");
    cell.append(saveButton, removeButton);
    return cell;
  }

  function renderItems() {
    if (!els.itemsBody) {
      return;
    }
    const watchlist = selectedWatchlist();
    els.itemsBody.replaceChildren();
    if (!watchlist || watchlist.items.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = watchlist
        ? copy("此列表尚无标的。", "This watchlist has no symbols yet.")
        : copy("先创建一个自选列表。", "Create a watchlist first.");
      row.append(cell);
      els.itemsBody.append(row);
      syncItemControls();
      return;
    }

    for (const item of watchlist.items) {
      const row = document.createElement("tr");
      row.dataset.itemId = item.id;
      row.append(createTextCell(item.symbol), createTextCell(item.asset_type));

      const notesCell = document.createElement("td");
      const notesInput = document.createElement("input");
      notesInput.type = "text";
      notesInput.value = item.notes || "";
      notesInput.dataset.watchlistItemNotes = item.id;
      notesInput.setAttribute("aria-label", copy(`${item.symbol} 备注`, `Notes for ${item.symbol}`));
      notesCell.append(notesInput);
      row.append(notesCell, createItemActions(item));
      els.itemsBody.append(row);
    }
    syncItemControls();
  }

  function syncItemControls() {
    const disabled = !selectedWatchlist();
    if (els.symbol) els.symbol.disabled = disabled;
    if (els.assetType) els.assetType.disabled = disabled;
    if (els.notes) els.notes.disabled = disabled;
    if (els.addItemButton) els.addItemButton.disabled = disabled;
  }

  function populateEditor(watchlist) {
    if (els.name) els.name.value = watchlist?.name || "";
    if (els.description) els.description.value = watchlist?.description || "";
    if (els.isDefault) els.isDefault.checked = Boolean(watchlist?.is_default);
    if (els.saveButton) {
      els.saveButton.textContent = state.editorMode === "create"
        ? copy("创建列表", "Create Watchlist")
        : copy("保存列表", "Save Watchlist");
    }
  }

  function ensureNewButton() {
    if (!els.form || !els.saveButton || document.getElementById("watchlist-new")) {
      return;
    }
    const button = document.createElement("button");
    button.id = "watchlist-new";
    button.className = "icon-button";
    button.type = "button";
    button.textContent = copy("新建列表", "New Watchlist");
    button.addEventListener("click", () => {
      state.editorMode = "create";
      populateEditor(null);
      els.name?.focus();
    });
    els.saveButton.before(button);
  }

  function openDialog() {
    if (!els.dialog) {
      return;
    }
    state.editorMode = selectedWatchlist() ? "edit" : "create";
    populateEditor(selectedWatchlist());
    renderItems();
    if (typeof els.dialog.showModal === "function") {
      if (!els.dialog.open) els.dialog.showModal();
    } else {
      els.dialog.setAttribute("open", "");
    }
    els.name?.focus();
  }

  function closeDialog() {
    if (!els.dialog) {
      return;
    }
    if (typeof els.dialog.close === "function") {
      els.dialog.close();
    } else {
      els.dialog.removeAttribute("open");
    }
  }

  function upsertWatchlist(watchlist) {
    if (watchlist.is_default) {
      state.watchlists = state.watchlists.map((existing) => ({ ...existing, is_default: false }));
    }
    const index = state.watchlists.findIndex((existing) => existing.id === watchlist.id);
    if (index === -1) {
      state.watchlists.unshift(watchlist);
    } else {
      state.watchlists[index] = watchlist;
    }
    renderSelect(watchlist.id);
    renderItems();
  }

  async function refreshResearch() {
    const refresh = window.StocksToolResearch?.refresh;
    if (typeof refresh !== "function") {
      return;
    }
    try {
      const refreshed = await refresh({
        watchlistId: getSelectedId(),
        accountId: document.getElementById("account-select")?.value || "",
      });
      const generatedAt = window.StocksToolResearch?.getState?.().generatedAt;
      if (refreshed && generatedAt) {
        window.StocksToolWorkspace?.updateDataTime?.(generatedAt);
      }
    } catch (error) {
      console.error(error);
      setStatus(
        copy(
          `自选上下文已更新，但研究台刷新失败：${error.message}`,
          `The watchlist context changed, but the research view failed to refresh: ${error.message}`,
        ),
        "warning",
      );
    }
  }

  async function refresh(options = {}) {
    const preferredId = options.preferredId ?? getSelectedId();
    const generation = ++state.refreshGeneration;
    try {
      const watchlists = await apiFetch("/watchlists");
      if (generation !== state.refreshGeneration) {
        return state.watchlists;
      }
      state.watchlists = Array.isArray(watchlists) ? watchlists : [];
      renderSelect(preferredId);
      renderItems();
      if (!options.quiet) {
        setStatus(copy(`已加载 ${state.watchlists.length} 个自选列表。`, `${state.watchlists.length} watchlist(s) loaded.`), "success");
      }
      return state.watchlists;
    } catch (error) {
      console.error(error);
      if (generation === state.refreshGeneration) {
        setStatus(
          copy(`自选列表刷新失败，继续显示现有数据：${error.message}`, `Watchlist refresh failed; existing data remains visible: ${error.message}`),
          "error",
        );
      }
      return state.watchlists;
    }
  }

  async function saveWatchlist(event) {
    event.preventDefault();
    const name = els.name?.value.trim() || "";
    if (!name) {
      setStatus(copy("自选列表名称不能为空。", "Watchlist name is required."), "error");
      els.name?.focus();
      return;
    }
    const current = selectedWatchlist();
    if (state.editorMode === "edit" && !current) {
      setStatus(copy("请选择要编辑的自选列表。", "Select a watchlist to edit."), "error");
      return;
    }
    const payload = {
      name,
      description: els.description?.value.trim() || null,
      is_default: Boolean(els.isDefault?.checked),
    };
    const isCreating = state.editorMode === "create";
    const url = isCreating ? "/watchlists" : `/watchlists/${encodeURIComponent(current.id)}`;
    els.saveButton.disabled = true;
    try {
      const saved = await apiFetch(url, {
        method: isCreating ? "POST" : "PATCH",
        body: JSON.stringify(payload),
      });
      upsertWatchlist(saved);
      state.editorMode = "edit";
      populateEditor(saved);
      setStatus(
        isCreating ? copy(`已创建自选列表 ${saved.name}。`, `Watchlist ${saved.name} created.`) : copy(`已更新自选列表 ${saved.name}。`, `Watchlist ${saved.name} updated.`),
        "success",
      );
      await refreshResearch();
    } catch (error) {
      console.error(error);
      setStatus(
        copy(`保存自选列表失败，现有数据未改变：${error.message}`, `Saving watchlist failed; existing data was not changed: ${error.message}`),
        "error",
      );
    } finally {
      els.saveButton.disabled = false;
    }
  }

  async function addItem(event) {
    event.preventDefault();
    const watchlist = selectedWatchlist();
    const symbol = els.symbol?.value.trim().toUpperCase() || "";
    if (!watchlist || !symbol) {
      setStatus(copy("请选择自选列表并输入标的代码。", "Select a watchlist and enter a symbol."), "error");
      return;
    }
    els.addItemButton.disabled = true;
    try {
      const updated = await apiFetch(`/watchlists/${encodeURIComponent(watchlist.id)}/items`, {
        method: "POST",
        body: JSON.stringify({
          symbol,
          asset_type: els.assetType?.value || "stock",
          notes: els.notes?.value.trim() || null,
        }),
      });
      upsertWatchlist(updated);
      if (els.symbol) els.symbol.value = "";
      if (els.notes) els.notes.value = "";
      setStatus(copy(`已将 ${symbol} 加入 ${updated.name}。`, `${symbol} added to ${updated.name}.`), "success");
      await refreshResearch();
    } catch (error) {
      console.error(error);
      setStatus(
        copy(`添加标的失败，现有数据未改变：${error.message}`, `Adding symbol failed; existing data was not changed: ${error.message}`),
        "error",
      );
    } finally {
      els.addItemButton.disabled = false;
      syncItemControls();
    }
  }

  async function saveItemNotes(button, itemId) {
    const watchlist = selectedWatchlist();
    const input = els.itemsBody?.querySelector(`[data-watchlist-item-notes="${CSS.escape(itemId)}"]`);
    if (!watchlist || !input) {
      return;
    }
    button.disabled = true;
    try {
      const updated = await apiFetch(
        `/watchlists/${encodeURIComponent(watchlist.id)}/items/${encodeURIComponent(itemId)}`,
        { method: "PATCH", body: JSON.stringify({ notes: input.value.trim() || null }) },
      );
      upsertWatchlist(updated);
      setStatus(copy("自选备注已更新。", "Watchlist notes updated."), "success");
      await refreshResearch();
    } catch (error) {
      console.error(error);
      setStatus(
        copy(`更新备注失败，现有数据未改变：${error.message}`, `Updating notes failed; existing data was not changed: ${error.message}`),
        "error",
      );
    } finally {
      button.disabled = false;
    }
  }

  async function deleteEmptyResponse(url) {
    const response = await fetch(url, { method: "DELETE", headers: { Accept: "application/json" } });
    if (response.ok) {
      return;
    }
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message || detail;
    } catch (_error) {
      // Keep the status-based detail when the response is not JSON.
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  async function removeItem(button, itemId) {
    const watchlist = selectedWatchlist();
    const item = watchlist?.items.find((candidate) => candidate.id === itemId);
    if (!watchlist || !item) {
      return;
    }
    const confirmed = window.confirm(
      copy(`确认从 ${watchlist.name} 移除 ${item.symbol}？`, `Remove ${item.symbol} from ${watchlist.name}?`),
    );
    if (!confirmed) {
      setStatus(copy("已取消移除标的。", "Symbol removal canceled."), "warning");
      return;
    }
    button.disabled = true;
    try {
      await deleteEmptyResponse(
        `/watchlists/${encodeURIComponent(watchlist.id)}/items/${encodeURIComponent(itemId)}`,
      );
      const updated = {
        ...watchlist,
        items: watchlist.items.filter((candidate) => candidate.id !== itemId),
      };
      upsertWatchlist(updated);
      setStatus(copy(`已从 ${watchlist.name} 移除 ${item.symbol}。`, `${item.symbol} removed from ${watchlist.name}.`), "success");
      await refreshResearch();
    } catch (error) {
      console.error(error);
      setStatus(
        copy(`移除标的失败，现有数据未改变：${error.message}`, `Removing symbol failed; existing data was not changed: ${error.message}`),
        "error",
      );
    } finally {
      button.disabled = false;
    }
  }

  function handleItemsClick(event) {
    const button = event.target.closest("[data-watchlist-action]");
    if (!button || !els.itemsBody?.contains(button)) {
      return;
    }
    const itemId = button.dataset.itemId;
    if (button.dataset.watchlistAction === "save-notes") {
      void saveItemNotes(button, itemId);
    } else if (button.dataset.watchlistAction === "remove-item") {
      void removeItem(button, itemId);
    }
  }

  function wireEvents() {
    els.select?.addEventListener("change", () => {
      state.editorMode = "edit";
      populateEditor(selectedWatchlist());
      renderItems();
      void refreshResearch();
    });
    els.manageButton?.addEventListener("click", openDialog);
    els.closeButton?.addEventListener("click", closeDialog);
    els.form?.addEventListener("submit", saveWatchlist);
    els.itemForm?.addEventListener("submit", addItem);
    els.itemsBody?.addEventListener("click", handleItemsClick);
  }

  async function init() {
    if (state.initialized) {
      return refresh({ quiet: true });
    }
    bindElements();
    if (!els.select) {
      return [];
    }
    state.initialized = true;
    ensureNewButton();
    wireEvents();
    return refresh({ quiet: true });
  }

  window.StocksToolWatchlists = {
    init,
    refresh,
    getSelectedId,
  };
})();
