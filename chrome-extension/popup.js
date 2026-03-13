document.addEventListener("DOMContentLoaded", () => {
  const crmUrl = document.getElementById("crmUrl");
  const empresaSlug = document.getElementById("empresaSlug");
  const apiKey = document.getElementById("apiKey");
  const saveBtn = document.getElementById("saveBtn");
  const status = document.getElementById("status");

  // Carregar configurações salvas
  chrome.storage.sync.get(["crmUrl", "empresaSlug", "apiKey"], (result) => {
    if (result.crmUrl) crmUrl.value = result.crmUrl;
    if (result.empresaSlug) empresaSlug.value = result.empresaSlug;
    if (result.apiKey) apiKey.value = result.apiKey;
  });

  // Salvar
  saveBtn.addEventListener("click", () => {
    const url = crmUrl.value.trim();
    const slug = empresaSlug.value.trim();
    const key = apiKey.value.trim();

    if (!url || !slug || !key) {
      status.textContent = "Preencha todos os campos";
      status.className = "status show error";
      return;
    }

    chrome.storage.sync.set(
      {
        crmUrl: url,
        empresaSlug: slug,
        apiKey: key,
      },
      () => {
        status.textContent = "Configurações salvas! Recarregue o WhatsApp Web.";
        status.className = "status show";
        setTimeout(() => {
          status.className = "status";
        }, 3000);
      }
    );
  });
});
