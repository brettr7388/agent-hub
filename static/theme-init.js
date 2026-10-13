// Runs before first paint: an explicit choice wins, otherwise follow the device's light or dark mode.
(() => {
  let choice = null;
  try { choice = localStorage.getItem('agent-hub-theme-choice') || (localStorage.getItem('agent-hub-theme') === 'dark' ? 'dark' : null); } catch { /* storage may be unavailable */ }
  const value = choice || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = value;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = value === 'light' ? '#ffffff' : '#212121';
})();
