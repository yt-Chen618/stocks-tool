(function () {
  "use strict";

  const MOBILE_QUERY = "(max-width: 780px)";
  const READONLY_FORM_SELECTOR = "#order-ticket-form, #replace-order-form, #journal-entry-form";

  let initialized = false;
  let lastFocus = null;
  let elements = {};

  function tabValue(element) {
    return element && (element.dataset.executionTab || element.value);
  }

  function panelValue(element) {
    return element && (element.dataset.executionPanel || element.value);
  }

  function attributeHasToken(value, token) {
    return String(value || "")
      .trim()
      .split(/\s+/)
      .includes(token);
  }

  function selectTab(value, options) {
    init();
    if (!elements.tabs.length) {
      return null;
    }
    const requested = String(value || "").trim();
    const selectedValue = elements.tabs.some((tab) => tabValue(tab) === requested)
      ? requested
      : tabValue(elements.tabs[0]);
    const shouldFocus = Boolean(options && options.focus);

    elements.tabs.forEach((tab) => {
      const selected = tabValue(tab) === selectedValue;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && shouldFocus) {
        tab.focus();
      }
    });
    elements.panels.forEach((panel) => {
      const selected = attributeHasToken(panelValue(panel), selectedValue);
      panel.hidden = !selected;
      panel.setAttribute("aria-hidden", String(!selected));
    });
    if (elements.drawer) {
      elements.drawer.dataset.executionTab = selectedValue;
    }
    return selectedValue;
  }

  function firstFocusTarget() {
    return elements.drawer?.querySelector(
      "[autofocus], [data-execution-tab][aria-selected='true'], button:not([disabled]), " +
        "a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), " +
        "[tabindex]:not([tabindex='-1'])",
    );
  }

  function open(options) {
    init();
    if (!elements.drawer) {
      return false;
    }
    const requestedTab = typeof options === "string" ? options : options && options.tab;
    if (requestedTab) {
      selectTab(requestedTab);
    }
    if (elements.drawer.open) {
      return true;
    }
    lastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    elements.drawer.showModal();
    elements.openButton?.setAttribute("aria-expanded", "true");
    firstFocusTarget()?.focus();
    return true;
  }

  function close() {
    init();
    if (!elements.drawer?.open) {
      return false;
    }
    elements.drawer.close();
    return true;
  }

  function handleClosed() {
    elements.openButton?.setAttribute("aria-expanded", "false");
    if (lastFocus && document.contains(lastFocus)) {
      lastFocus.focus();
    } else {
      elements.openButton?.focus();
    }
    lastFocus = null;
  }

  function setMobileReadonlyInternal(blocked) {
    const readonly = Boolean(blocked);
    if (!elements.drawer) {
      return readonly;
    }
    elements.drawer.dataset.mobileReadonly = String(readonly);
    elements.drawer.querySelectorAll(READONLY_FORM_SELECTOR).forEach((form) => {
      form.toggleAttribute("inert", readonly);
      form.setAttribute("aria-disabled", String(readonly));
    });
    return readonly;
  }

  function setMobileReadonly(blocked) {
    init();
    return setMobileReadonlyInternal(blocked);
  }

  function handleTabArrow(event, currentIndex) {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % elements.tabs.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + elements.tabs.length) % elements.tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = elements.tabs.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    selectTab(tabValue(elements.tabs[nextIndex]), { focus: true });
  }

  function bindTabs() {
    elements.panels.forEach((panel, index) => {
      panel.id ||= `execution-panel-${index + 1}`;
      panel.setAttribute("role", "tabpanel");
    });
    elements.tabs.forEach((tab, index) => {
      const value = tabValue(tab);
      tab.id ||= `execution-tab-${value}`;
      tab.setAttribute("role", "tab");
      tab.setAttribute(
        "aria-controls",
        elements.panels
          .filter((panel) => attributeHasToken(panelValue(panel), value))
          .map((panel) => panel.id)
          .join(" "),
      );
      tab.addEventListener("click", () => selectTab(value));
      tab.addEventListener("keydown", (event) => handleTabArrow(event, index));
    });
    elements.panels.forEach((panel) => {
      const labels = elements.tabs
        .filter((tab) => attributeHasToken(panelValue(panel), tabValue(tab)))
        .map((tab) => tab.id);
      panel.setAttribute("aria-labelledby", labels.join(" "));
    });
    selectTab();
  }

  function init() {
    if (initialized) {
      return window.StocksToolExecution;
    }
    elements = {
      drawer: document.getElementById("execution-drawer"),
      openButton: document.getElementById("open-execution-drawer"),
      closeButton: document.getElementById("close-execution-drawer"),
      tabs: Array.from(document.querySelectorAll("[data-execution-tab]")),
      panels: Array.from(document.querySelectorAll("[data-execution-panel]")),
    };
    elements.openButton?.setAttribute("aria-controls", "execution-drawer");
    elements.openButton?.setAttribute("aria-expanded", "false");
    elements.openButton?.addEventListener("click", () => open());
    elements.closeButton?.addEventListener("click", close);
    elements.drawer?.addEventListener("close", handleClosed);
    initialized = true;
    bindTabs();
    const mobile = window.matchMedia?.(MOBILE_QUERY).matches ?? window.innerWidth <= 780;
    setMobileReadonlyInternal(mobile);
    return window.StocksToolExecution;
  }

  window.StocksToolExecution = {
    init,
    open,
    close,
    selectTab,
    setMobileReadonly,
  };
})();
