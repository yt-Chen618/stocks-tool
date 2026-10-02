(function () {
  "use strict";

  const WORKSPACE_STORAGE_KEY = "stocks-tool-workspace";
  const SIDEBAR_STORAGE_KEY = "stocks-tool-sidebar-collapsed";
  const DEFAULT_WORKSPACE = "research";

  let initialized = false;
  let elements = {};
  let topbarResizeObserver = null;

  function readStorage(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_error) {
      // The workbench remains usable when storage is blocked.
    }
  }

  function workspaceValue(element) {
    return element && (element.dataset.workspaceOption || element.value);
  }

  function panelValue(element) {
    return element && (element.dataset.workspacePanel || element.value);
  }

  function strategyTabValue(element) {
    return element && (element.dataset.strategyTab || element.value);
  }

  function attributeHasToken(value, token) {
    return String(value || "")
      .trim()
      .split(/\s+/)
      .includes(token);
  }

  function availableWorkspace(value) {
    return elements.workspaceOptions.some((option) => workspaceValue(option) === value);
  }

  function selectWorkspace(value, options) {
    const requested = String(value || "").trim();
    const workspace = availableWorkspace(requested) ? requested : DEFAULT_WORKSPACE;
    const shouldFocus = Boolean(options && options.focus);

    document.body.dataset.workspace = workspace;
    elements.workspaceOptions.forEach((option) => {
      const selected = workspaceValue(option) === workspace;
      option.classList.toggle("is-active", selected);
      option.setAttribute("aria-selected", String(selected));
      option.setAttribute("aria-current", selected ? "page" : "false");
      option.tabIndex = selected ? 0 : -1;
      if (selected && shouldFocus) {
        option.focus();
      }
    });
    elements.workspacePanels.forEach((panel) => {
      const selected = panelValue(panel) === workspace;
      panel.hidden = !selected;
      panel.setAttribute("aria-hidden", String(!selected));
    });
    writeStorage(WORKSPACE_STORAGE_KEY, workspace);
    return workspace;
  }

  function setSidebarCollapsed(collapsed, persist) {
    const isCollapsed = Boolean(collapsed);
    document.body.dataset.sidebarCollapsed = String(isCollapsed);
    if (elements.appShell) {
      elements.appShell.classList.toggle("sidebar-collapsed", isCollapsed);
    }
    if (elements.sidebar) {
      elements.sidebar.classList.toggle("is-collapsed", isCollapsed);
    }
    if (elements.sidebarToggle) {
      elements.sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
      elements.sidebarToggle.setAttribute(
        "aria-label",
        isCollapsed ? "Expand workspace navigation" : "Collapse workspace navigation",
      );
    }
    if (persist !== false) {
      writeStorage(SIDEBAR_STORAGE_KEY, String(isCollapsed));
    }
  }

  function toggleSidebar() {
    setSidebarCollapsed(document.body.dataset.sidebarCollapsed !== "true");
  }

  function selectStrategyTab(value, options) {
    const requested = String(value || "").trim();
    const tabs = elements.strategyTabs;
    if (!tabs.length) {
      return null;
    }
    const selectedValue = tabs.some((tab) => strategyTabValue(tab) === requested)
      ? requested
      : "bull-put";
    const shouldFocus = Boolean(options && options.focus);

    tabs.forEach((tab) => {
      const selected = strategyTabValue(tab) === selectedValue;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && shouldFocus) {
        tab.focus();
      }
    });
    elements.strategyPanels.forEach((panel) => {
      const selected = attributeHasToken(panel.dataset.strategyCategory, selectedValue);
      panel.hidden = !selected;
      panel.setAttribute("aria-hidden", String(!selected));
    });
    elements.strategySubpanels.forEach((panel) => {
      const selected = attributeHasToken(panel.dataset.strategySubcategory, selectedValue);
      panel.hidden = !selected;
      panel.setAttribute("aria-hidden", String(!selected));
    });
    if (elements.strategySection) {
      elements.strategySection.dataset.strategyTab = selectedValue;
    }
    return selectedValue;
  }

  function openExecutionDrawer(options) {
    window.StocksToolExecution?.init();
    return window.StocksToolExecution?.open(options) ?? false;
  }

  function closeExecutionDrawer() {
    window.StocksToolExecution?.init();
    return window.StocksToolExecution?.close() ?? false;
  }

  function updateAccountContext(value) {
    if (elements.accountContext) {
      elements.accountContext.textContent = value == null || value === "" ? "--" : String(value);
    }
  }

  function updateDataTime(value) {
    if (!elements.dataTime) {
      return;
    }
    if (value == null || value === "") {
      elements.dataTime.textContent = "--";
      elements.dataTime.removeAttribute("datetime");
      return;
    }
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isNaN(date.getTime())) {
      elements.dataTime.textContent = new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
      elements.dataTime.setAttribute("datetime", date.toISOString());
    } else {
      elements.dataTime.textContent = String(value);
      elements.dataTime.removeAttribute("datetime");
    }
  }

  function syncTopbarOffset() {
    const topbar = elements.topbar;
    if (!topbar) return;
    const height = Math.ceil(topbar.getBoundingClientRect().height);
    if (!Number.isFinite(height) || height <= 0) return;
    const nextValue = `${height}px`;
    const currentValue = document.documentElement.style.getPropertyValue("--workspace-topbar-offset").trim();
    if (currentValue !== nextValue) {
      document.documentElement.style.setProperty("--workspace-topbar-offset", nextValue);
    }
  }

  function observeTopbar() {
    syncTopbarOffset();
    if (typeof ResizeObserver === "function" && elements.topbar) {
      topbarResizeObserver = new ResizeObserver(() => syncTopbarOffset());
      topbarResizeObserver.observe(elements.topbar);
    }
    window.addEventListener("resize", syncTopbarOffset, { passive: true });
  }

  function handleTabArrow(event, items, currentIndex, activate) {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % items.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + items.length) % items.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = items.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    activate(items[nextIndex]);
  }

  function bindWorkspaceNavigation() {
    elements.workspaceOptions.forEach((option, index) => {
      option.setAttribute("role", "tab");
      option.addEventListener("click", () => selectWorkspace(workspaceValue(option)));
      option.addEventListener("keydown", (event) => {
        handleTabArrow(event, elements.workspaceOptions, index, (target) => {
          selectWorkspace(workspaceValue(target), { focus: true });
        });
      });
    });
    if (elements.sidebar) {
      elements.sidebar.setAttribute("aria-label", "Workspace navigation");
    }
    if (elements.sidebarToggle) {
      elements.sidebarToggle.addEventListener("click", toggleSidebar);
    }
  }

  function bindStrategyTabs() {
    elements.strategyPanels.forEach((panel, index) => {
      panel.id ||= `strategy-panel-${index + 1}`;
      panel.setAttribute("role", "tabpanel");
    });
    elements.strategyTabs.forEach((tab, index) => {
      const value = strategyTabValue(tab);
      tab.id ||= `strategy-tab-${value}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute(
        "aria-controls",
        elements.strategyPanels
          .filter((panel) => attributeHasToken(panel.dataset.strategyCategory, value))
          .map((panel) => panel.id)
          .join(" "),
      );
      tab.addEventListener("click", () => selectStrategyTab(strategyTabValue(tab)));
      tab.addEventListener("keydown", (event) => {
        handleTabArrow(event, elements.strategyTabs, index, (target) => {
          selectStrategyTab(strategyTabValue(target), { focus: true });
        });
      });
    });
    elements.strategyPanels.forEach((panel) => {
      const labels = elements.strategyTabs
        .filter((tab) => attributeHasToken(panel.dataset.strategyCategory, strategyTabValue(tab)))
        .map((tab) => tab.id);
      panel.setAttribute("aria-labelledby", labels.join(" "));
    });
    selectStrategyTab("bull-put");
  }

  function relocateWorkspacePanels() {
    const macroGrid = document.getElementById("macro-workspace-grid");
    if (!macroGrid) {
      return;
    }
    document.querySelectorAll('[data-workspace-relocate="macro"]').forEach((panel) => {
      macroGrid.appendChild(panel);
    });
  }

  function init() {
    if (initialized) {
      return window.StocksToolWorkspace;
    }
    relocateWorkspacePanels();
    elements = {
      appShell: document.getElementById("app-shell"),
      sidebar: document.getElementById("workspace-sidebar"),
      sidebarToggle: document.getElementById("sidebar-toggle"),
      topbar: document.querySelector(".workspace-topbar"),
      workspaceOptions: Array.from(document.querySelectorAll("[data-workspace-option]")),
      workspacePanels: Array.from(document.querySelectorAll("[data-workspace-panel]")),
      accountContext: document.getElementById("topbar-account-context"),
      dataTime: document.getElementById("topbar-data-time"),
      strategyTabs: Array.from(document.querySelectorAll("[data-strategy-tab]")),
      strategyPanels: Array.from(document.querySelectorAll("[data-strategy-category]")),
      strategySubpanels: Array.from(document.querySelectorAll("[data-strategy-subcategory]")),
      strategySection: document.getElementById("strategy-section"),
    };

    bindWorkspaceNavigation();
    bindStrategyTabs();
    observeTopbar();
    setSidebarCollapsed(readStorage(SIDEBAR_STORAGE_KEY) === "true", false);
    selectWorkspace(readStorage(WORKSPACE_STORAGE_KEY) || DEFAULT_WORKSPACE);
    initialized = true;
    return window.StocksToolWorkspace;
  }

  window.StocksToolWorkspace = {
    init,
    selectWorkspace,
    openExecutionDrawer,
    closeExecutionDrawer,
    updateAccountContext,
    updateDataTime,
  };
})();
