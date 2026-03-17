/**
 * CRM WhatsApp Web Extension
 * Injeta botão "Salvar no CRM" com formulário de pipeline.
 */

(function () {
  "use strict";

  let debounceTimer = null;
  let lastHeaderText = null;
  let pipelinesCache = null;

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
    }, 4000);
  }

  // ==================== EXTRAIR DADOS ====================

  function extractContactInfo() {
    let name = null;
    let phone = null;

    // 1. Pegar nome/número do header do chat
    const header = document.querySelector("#main header");
    if (header) {
      // Tentar múltiplos seletores para o nome do contato
      const nameSelectors = [
        'span[title][dir="auto"]',
        "span[title]",
      ];
      for (const sel of nameSelectors) {
        const spans = header.querySelectorAll(sel);
        for (const span of spans) {
          const title = (span.getAttribute("title") || "").trim();
          if (!title) continue;
          if (title.toLowerCase().includes("clique")) continue;
          if (title.toLowerCase().includes("click")) continue;
          if (title.toLowerCase().includes("etiquetar")) continue;
          if (title.toLowerCase().includes("pesquisar")) continue;
          if (title.toLowerCase().includes("silenciar")) continue;
          if (title.toLowerCase().includes("adicionar")) continue;
          if (title.length > 100) continue;

          name = title;
          break;
        }
        if (name) break;
      }
    }

    // Fallback: tentar pegar o textContent do primeiro elemento clicável do header
    if (!name && header) {
      const clickable = header.querySelector('[role="button"] span, [data-testid] span');
      if (clickable) {
        const txt = (clickable.textContent || "").trim();
        if (txt && txt.length < 50 && !txt.toLowerCase().includes("clique")) {
          name = txt;
        }
      }
    }

    // 2. Extrair telefone do nome se for um número (+55 XX XXXXX-XXXX)
    if (name) {
      const nameDigits = name.replace(/\D/g, "");
      if (nameDigits.length >= 10 && nameDigits.length <= 15) {
        phone = nameDigits;
      }
    }

    // 3. Se não achou telefone, procurar no painel de info do contato (drawer lateral)
    if (!phone) {
      // O painel de contato tem o número em um span visível
      const drawerSelectors = [
        'div[data-testid="contact-info-drawer"] span[title]',
        'section span[title*="+55"]',
        'section span[title*="+"]',
      ];
      for (const sel of drawerSelectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          const txt = (el.getAttribute("title") || el.textContent || "").trim();
          const digits = txt.replace(/\D/g, "");
          if (digits.length >= 10 && digits.length <= 15) {
            phone = digits;
            if (!name || name === txt) name = txt;
            break;
          }
        }
        if (phone) break;
      }
    }

    // 4. Último recurso: procurar qualquer texto com formato de telefone BR no #main header
    if (!phone && header) {
      const allText = header.textContent || "";
      const phoneMatch = allText.match(/\+?55\s*\d{2}\s*\d{4,5}[\s\-]?\d{4}/);
      if (phoneMatch) {
        phone = phoneMatch[0].replace(/\D/g, "");
      }
    }

    console.log("[CRM Extension] Extraído:", { name, phone });
    return { name, phone };
  }

  // ==================== API ====================

  async function apiCall(endpoint, method, body) {
    const config = await getConfig();
    if (!config.crmUrl || !config.apiKey || !config.empresaSlug) {
      showFeedback("Configure a extensão primeiro (clique no ícone)", "error");
      return null;
    }

    const url = `${config.crmUrl.replace(/\/$/, "")}/api/v1/leads/chrome-extension/${config.empresaSlug}/${endpoint}`;
    const options = {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": config.apiKey,
      },
    };
    if (body) options.body = JSON.stringify(body);

    const response = await fetch(url, options);
    return await response.json();
  }

  async function loadPipelines() {
    if (pipelinesCache) return pipelinesCache;
    try {
      const result = await apiCall("pipelines/", "GET");
      if (result && result.pipelines) {
        pipelinesCache = result.pipelines;
        return pipelinesCache;
      }
    } catch (e) {
      console.error("[CRM Extension] Erro ao carregar pipelines:", e);
    }
    return [];
  }

  // ==================== FORMULÁRIO ====================

  function createFormModal() {
    // Remover se existir
    const old = document.getElementById("crm-modal");
    if (old) old.remove();

    const overlay = document.createElement("div");
    overlay.id = "crm-modal";
    overlay.innerHTML = `
      <div class="crm-modal-backdrop"></div>
      <div class="crm-modal-content">
        <div class="crm-modal-header">Salvar no CRM</div>
        <div class="crm-modal-body">
          <div class="crm-field">
            <label>Nome</label>
            <input type="text" id="crm-nome" placeholder="Nome do contato">
          </div>
          <div class="crm-field">
            <label>Telefone</label>
            <input type="text" id="crm-telefone" placeholder="DDD + Número">
          </div>
          <div class="crm-field">
            <label>Pipeline</label>
            <select id="crm-pipeline">
              <option value="">Sem pipeline (salvar como Lead)</option>
            </select>
          </div>
          <div class="crm-field" id="crm-etapa-field" style="display:none">
            <label>Etapa</label>
            <select id="crm-etapa"></select>
          </div>
          <div class="crm-field">
            <label>Notas</label>
            <textarea id="crm-notas" rows="2" placeholder="Observações (opcional)"></textarea>
          </div>
        </div>
        <div class="crm-modal-footer">
          <button class="crm-btn-cancel" id="crm-cancel">Cancelar</button>
          <button class="crm-btn-save" id="crm-save">Salvar</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Eventos
    overlay.querySelector(".crm-modal-backdrop").addEventListener("click", closeModal);
    document.getElementById("crm-cancel").addEventListener("click", closeModal);
    document.getElementById("crm-save").addEventListener("click", handleFormSave);
    document.getElementById("crm-pipeline").addEventListener("change", onPipelineChange);

    return overlay;
  }

  function closeModal() {
    const modal = document.getElementById("crm-modal");
    if (modal) modal.remove();
  }

  function onPipelineChange() {
    const pipelineId = document.getElementById("crm-pipeline").value;
    const etapaField = document.getElementById("crm-etapa-field");
    const etapaSelect = document.getElementById("crm-etapa");

    if (!pipelineId || !pipelinesCache) {
      etapaField.style.display = "none";
      return;
    }

    const pipeline = pipelinesCache.find((p) => String(p.id) === pipelineId);
    if (!pipeline || !pipeline.etapas.length) {
      etapaField.style.display = "none";
      return;
    }

    etapaSelect.innerHTML = "";
    pipeline.etapas.forEach((e) => {
      const opt = document.createElement("option");
      opt.value = e.id;
      opt.textContent = e.nome;
      etapaSelect.appendChild(opt);
    });

    etapaField.style.display = "block";
  }

  async function openForm() {
    const { name, phone } = extractContactInfo();
    const pipelines = await loadPipelines();

    createFormModal();

    // Preencher dados
    document.getElementById("crm-nome").value = name || "";
    document.getElementById("crm-telefone").value = phone || "";

    // Preencher pipelines
    const select = document.getElementById("crm-pipeline");
    pipelines.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.nome;
      select.appendChild(opt);
    });

    // Se só tem 1 pipeline, selecionar automaticamente
    if (pipelines.length === 1) {
      select.value = pipelines[0].id;
      onPipelineChange();
    }
  }

  async function handleFormSave() {
    const nome = document.getElementById("crm-nome").value.trim();
    const telefone = document.getElementById("crm-telefone").value.trim();
    const pipelineId = document.getElementById("crm-pipeline").value;
    const etapaId = document.getElementById("crm-etapa").value;
    const notas = document.getElementById("crm-notas").value.trim();

    if (!telefone) {
      showFeedback("Telefone é obrigatório", "error");
      return;
    }

    const saveBtn = document.getElementById("crm-save");
    saveBtn.textContent = "Salvando...";
    saveBtn.disabled = true;

    try {
      const body = {
        telefone: telefone.replace(/\D/g, ""),
        nome: nome || "Contato WhatsApp",
        notas,
        tags: ["whatsapp-web", "chrome-extension"],
      };
      if (pipelineId) body.pipeline_id = parseInt(pipelineId);
      if (etapaId) body.etapa_id = parseInt(etapaId);

      const result = await apiCall("", "POST", body);
      if (!result) return;

      if (result.status === "created") {
        const extra = result.pipeline ? ` → ${result.pipeline} / ${result.etapa}` : "";
        showFeedback(`${nome || "Contato"} salvo no CRM${extra}`, "success");
        closeModal();
        updateButtonState(result);
      } else if (result.status === "existing") {
        showFeedback(result.message, "info");
        closeModal();
      } else {
        throw new Error(result.error || "Erro desconhecido");
      }
    } catch (err) {
      showFeedback(`Erro: ${err.message}`, "error");
      saveBtn.textContent = "Salvar";
      saveBtn.disabled = false;
    }
  }

  function updateButtonState(result) {
    const btn = document.getElementById("crm-save-btn");
    if (!btn) return;
    btn.classList.add("crm-saved");
    if (result.pipeline) {
      btn.innerHTML = `&#9989; ${result.pipeline}`;
    } else {
      btn.innerHTML = "&#9989; Salvo!";
    }
    setTimeout(() => {
      btn.className = "";
      btn.id = "crm-save-btn";
      btn.innerHTML = "&#128190; Salvar no CRM";
    }, 5000);
  }

  // ==================== BOTÃO ====================

  function createButton() {
    const btn = document.createElement("button");
    btn.id = "crm-save-btn";
    btn.innerHTML = "&#128190; Salvar no CRM";
    btn.addEventListener("click", openForm);
    return btn;
  }

  // ==================== INJEÇÃO ====================

  function injectButton() {
    const header = document.querySelector("#main header");
    if (!header) return;

    const titleEl = header.querySelector("span[title]");
    const currentTitle = titleEl ? titleEl.getAttribute("title") : null;

    if (document.getElementById("crm-save-btn") && currentTitle === lastHeaderText) {
      return;
    }

    lastHeaderText = currentTitle;

    const existing = document.getElementById("crm-save-btn");
    if (existing) existing.remove();

    const btn = createButton();

    const actionsContainer = header.querySelector(
      'div[role="toolbar"], span[data-testid="menu"]'
    );
    if (actionsContainer) {
      actionsContainer.parentNode.insertBefore(btn, actionsContainer);
    } else {
      header.appendChild(btn);
    }

    // Verificar se contato já existe
    const { phone } = extractContactInfo();
    if (phone) {
      apiCall(`check/?telefone=${phone}`, "GET").then((result) => {
        if (result && result.exists) {
          btn.classList.add("crm-exists");
          if (result.pipelines && result.pipelines.length > 0) {
            const p = result.pipelines[0];
            btn.innerHTML = `&#128204; ${p.pipeline}: ${p.etapa || "sem etapa"}`;
          } else if (result.is_customer) {
            btn.innerHTML = `&#128204; Cliente: ${result.customer_nome}`;
          } else if (result.is_lead) {
            btn.innerHTML = `&#128204; Lead: ${result.lead_nome}`;
          }
        }
      });
    }
  }

  // ==================== OBSERVER ====================

  function onDomChange() {
    if (debounceTimer) return;
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      if (document.querySelector("#main")) {
        injectButton();
      }
    }, 500);
  }

  function startObserver() {
    const app = document.querySelector("#app");
    if (app) {
      new MutationObserver(onDomChange).observe(app, {
        childList: true,
        subtree: true,
      });
    }
  }

  // ==================== INIT ====================

  function waitForWhatsApp() {
    const check = setInterval(() => {
      if (document.querySelector("#app")) {
        clearInterval(check);
        console.log("[CRM Extension] WhatsApp Web detectado, iniciando...");
        startObserver();
        setTimeout(injectButton, 2000);
        // Pre-carregar pipelines
        loadPipelines();
      }
    }, 1000);
  }

  waitForWhatsApp();
})();
