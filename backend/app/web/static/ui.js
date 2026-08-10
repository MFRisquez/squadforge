(() => {
  // Soft focus helper for flashes
  const flash = document.querySelector(".flash");
  if (flash) {
    flash.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Mark drawer sheets for enter animation when opened
  const observer = new MutationObserver(() => {
    document.querySelectorAll(".drawer:not([hidden]) .drawer-sheet").forEach((el) => {
      el.classList.add("sheet-in");
    });
  });
  observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ["hidden"] });
})();
