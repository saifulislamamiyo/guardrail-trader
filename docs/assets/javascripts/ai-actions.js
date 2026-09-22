// "Copy page": fetch this page's Markdown source (raw.githubusercontent.com allows CORS) and copy it.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest('.ai-actions [data-ai="copy"]');
  if (!btn) return;
  const label = btn.textContent;
  try {
    const res = await fetch(btn.dataset.src, { credentials: "omit" });
    if (!res.ok) throw new Error(res.status);
    await navigator.clipboard.writeText(await res.text());
    btn.textContent = "Copied ✓";
  } catch (err) {
    btn.textContent = "Copy failed: use View as Markdown";
  }
  setTimeout(() => { btn.textContent = label; }, 2500);
});
