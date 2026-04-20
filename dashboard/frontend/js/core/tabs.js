export function initTabs({ onTabSelected } = {}) {
  const buttons = document.querySelectorAll(".tab-btn");
  if (!buttons.length) return;

  buttons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tab = btn.dataset.tab;
      if (!tab) return;

      buttons.forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");

      if (typeof onTabSelected === "function") {
        await onTabSelected(tab);
      }
    });
  });
}
