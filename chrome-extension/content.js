/**
 * CRM WhatsApp Web Extension
 * Injeta botão "Salvar no CRM" no header do chat aberto.
 */

(function () {
  "use strict";

  let currentPhone = null;
  let currentName = null;
  let btnInjected = false;

  // ==================== CONFIG ====================

  function getConfig() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(
        ["crmUrl", "apiKey", "empresaSlug"],
        (result) => {
          resolve({
            crmUrl: result.crmUrl || "",
            apiKey: result.apiKey || "",
            empresaSlug: result.empresaSlug || "",
          });
        }
      );
    });
  }

  // ==================== FEEDBACK ====================

  function showFeedback(message, type) {
    let el = document.getElementById("crm-feedback");
    if (!el) {
      el = document.createElement("div");
      el.id = "crm-feedback";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.className = `show ${type}`;
    setTimeout(() => {
      el.className = "";
    }, 3000);
  }

  // ==================== EXTRAIR DADOS ====================

  function extractContactInfo() {
    // Tentar pegar nome do header do chat
    // WhatsApp Web usa diferentes seletores dependendo da versão
    const headerSelectors = [
      'header span[dir="auto"][title]',
      "#main header span[title]",
      'div[data-testid="conversation-header"] span[title]',
      'div[data-testid="conversation-info-header"] span[title]',
    ];

    let name = null;
    for (const sel of headerSelectors) {
      const el = document.querySelector(sel);
      if (el) {
        name = el.getAttribute("title") || el.textContent;
        if (name && name.trim()) {
          name = name.trim();
          break;
        }
      }
    }

    // Tentar extrair telefone
    // O telefone pode estar no título se for um número não salvo
    // Ou podemos pegar do painel de info do contato
    let phone = null;

    // Se o nome parece ser um número de telefone
    if (name && /^[\d\s\+\-\(\)]+$/.test(name.replace(/\s/g, ""))) {
      phone = name.replace(/\D/g, "");
    }

    // Tentar pegar da seção de detalhes do contato
    if (!phone) {
      const phoneSelectors = [
        'span[title*="+55"]',
        'span.selectable-text[title*="+"]',
        'div[data-testid="chat-subtitle"] span',
      ];
      for (const sel of phoneSelectors) {
        const el = document.querySelector(sel);
        if (el) {
          const txt = el.getAttribute("title") || el.textContent || "";
          const digits = txt.replace(/\D/g, "");
          if (digits.length >= 10) {
            phone = digits;
            break;
          }
        }
      }
    }

    return { name, phone };
  }

  // ==================== API ====================

  async function saveToAPI(name, phone) {
    const config = await getConfig();

    if (!config.crmUrl || !config.apiKey || !config.empresaSlug) {
      showFeedback(
        "Configure a extensão primeiro (clique no ícone)",
        "error"
      );
      return null;
    }

    const url = `${config.crmUrl.replace(/\/$/, "")}/api/v1/leads/chrome-extension/${config.empresaSlug}/`;

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": config.apiKey,
      },
      body: JSON.stringify({
        telefone: phone,
        nome: name,
        tags: ["whatsapp-web", "chrome-extension"],
      }),
    });

    return await response.json();
  }

  async function checkContact(phone) {
    const config = await getConfig();
    if (!config.crmUrl || !config.apiKey || !config.empresaSlug) return null;

    const url = `${config.crmUrl.replace(/\/$/, "")}/api/v1/leads/chrome-extension/${config.empresaSlug}/check/?telefone=${phone}`;

    try {
      const response = await fetch(url, {
        headers: { "X-API-Key": config.apiKey },
      });
      return await response.json();
    } catch {
      return null;
    }
  }

  // ==================== BOTÃO ====================

  function createButton() {
    const btn = document.createElement("button");
    btn.id = "crm-save-btn";
    btn.innerHTML = "&#128190; Salvar no CRM";
    btn.addEventListener("click", handleSave);
    return btn;
  }

  async function handleSave() {
    const btn = document.getElementById("crm-save-btn");
    if (!btn) return;

    const { name, phone } = extractContactInfo();

    if (!phone) {
      // Pedir telefone manualmente
      const input = prompt(
        "Não consegui extrair o telefone automaticamente.\nDigite o número (com DDD):",
        ""
      );
      if (!input) return;
      currentPhone = input.replace(/\D/g, "");
    } else {
      currentPhone = phone;
    }

    currentName = name || "Contato WhatsApp";

    // Feedback visual
    btn.classList.add("crm-saving");
    btn.innerHTML = "&#8987; Salvando...";

    try {
      const result = await saveToAPI(currentName, currentPhone);
      if (!result) return;

      if (result.status === "created") {
        btn.classList.remove("crm-saving");
        btn.classList.add("crm-saved");
        btn.innerHTML = "&#9989; Salvo!";
        const extra = result.is_customer ? " (já é cliente!)" : "";
        showFeedback(`${currentName} salvo no CRM${extra}`, "success");
      } else if (result.status === "existing") {
        btn.classList.remove("crm-saving");
        btn.classList.add("crm-exists");
        btn.innerHTML = "&#128204; Já existe";
        showFeedback(
          `${result.message} - Status: ${result.lead_status}`,
          "info"
        );
      } else {
        throw new Error(result.error || "Erro desconhecido");
      }
    } catch (err) {
      btn.classList.remove("crm-saving");
      btn.classList.add("crm-error");
      btn.innerHTML = "&#10060; Erro";
      showFeedback(`Erro: ${err.message}`, "error");
    }

    // Resetar botão após 3 segundos
    setTimeout(() => {
      if (btn) {
        btn.className = "";
        btn.id = "crm-save-btn";
        btn.innerHTML = "&#128190; Salvar no CRM";
      }
    }, 3000);
  }

  // ==================== INJEÇÃO ====================

  function injectButton() {
    // Remover botão anterior se existir
    const existing = document.getElementById("crm-save-btn");
    if (existing) existing.remove();

    // Encontrar o header do chat
    const headerSelectors = [
      "#main header",
      'div[data-testid="conversation-header"]',
      'header[data-testid="chatlist-header"]',
    ];

    let header = null;
    for (const sel of headerSelectors) {
      header = document.querySelector(sel);
      if (header) break;
    }

    if (!header) return;

    // Verificar se já tem o botão neste header
    if (header.querySelector("#crm-save-btn")) return;

    const btn = createButton();

    // Inserir o botão no header
    // Tentar colocar ao lado dos ícones de ação
    const actionsContainer = header.querySelector(
      'div[role="toolbar"], span[data-testid="menu"]'
    );
    if (actionsContainer) {
      actionsContainer.parentNode.insertBefore(btn, actionsContainer);
    } else {
      header.appendChild(btn);
    }

    // Verificar se contato já existe no CRM
    const { phone } = extractContactInfo();
    if (phone) {
      checkContact(phone).then((result) => {
        if (result && result.exists) {
          btn.classList.add("crm-exists");
          const label = result.is_customer
            ? `Cliente: ${result.customer_nome}`
            : `Lead: ${result.lead_nome}`;
          btn.innerHTML = `&#128204; ${label}`;
        }
      });
    }
  }

  // ==================== OBSERVER ====================

  // Observar mudanças no DOM para detectar troca de chat
  function startObserver() {
    const observer = new MutationObserver(() => {
      // Verificar se tem um chat aberto
      const main = document.querySelector("#main");
      if (main) {
        injectButton();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  // ==================== INIT ====================

  // Esperar WhatsApp Web carregar
  function waitForWhatsApp() {
    const check = setInterval(() => {
      const app = document.querySelector("#app");
      if (app) {
        clearInterval(check);
        console.log("[CRM Extension] WhatsApp Web detectado, iniciando...");
        startObserver();
        // Tentar injetar imediatamente se já tem chat aberto
        setTimeout(injectButton, 2000);
      }
    }, 1000);
  }

  waitForWhatsApp();
})();
