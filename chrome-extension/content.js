/**
 * CRM WhatsApp Web Extension
 * Injeta botão "Salvar no CRM" com formulário de pipeline.
 */

(function () {
  "use strict";

  let debounceTimer = null;
  let lastHeaderText = null;
  let pipelinesCache = null;

  // Pipeline cujas etapas viram botões de atalho de 1-clique no header.
  // Identificada pelo slug (não por ID, que varia por empresa).
  const QUICK_PIPELINE_SLUG = "pos-venda-atrasos";

  // De-para: nome da LISTA nativa do WhatsApp -> SLUG da etapa no CRM.
  // Chave em minúsculas (match case-insensitive). A etapa é resolvida pela
  // pipeline carregada, então o slug precisa bater com PipelineEtapa.slug.
  const LISTA_PARA_ETAPA = {
    "consulta": "consulta",
    "atrasado": "atrasado",
    "atrasado sair hoje": "urgente",
    "aguardando rastreio": "aguardando-codigo-rastreio",
    "sapato errado": "sapato-errado",
    "resolvido": "resolvido",
  };

  // Prioridade quando a conversa está em várias listas mapeadas (maior = vence).
  const ETAPA_PRIORIDADE = {
    "sapato-errado": 6,
    "urgente": 5,
    "atrasado": 4,
    "aguardando-codigo-rastreio": 3,
    "consulta": 2,
    "resolvido": 1,
  };

  // Evita re-disparar auto-save para a mesma conversa repetidamente.
  let autoSavedKey = null;

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
    let headerText = null;

    // 1. Pegar nome/número do header do chat
    const header = document.querySelector("#main header");
    if (header) {
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

          headerText = title;
          break;
        }
        if (headerText) break;
      }
    }

    // Fallback: tentar pegar o textContent do primeiro elemento clicável do header
    if (!headerText && header) {
      const clickable = header.querySelector('[role="button"] span, [data-testid] span');
      if (clickable) {
        const txt = (clickable.textContent || "").trim();
        if (txt && txt.length < 50 && !txt.toLowerCase().includes("clique")) {
          headerText = txt;
        }
      }
    }

    // 2. Verificar se o header é um número de telefone
    if (headerText) {
      const headerDigits = headerText.replace(/\D/g, "");
      if (headerDigits.length >= 10 && headerDigits.length <= 15) {
        // Header é um telefone, não um nome
        phone = headerDigits;
      } else {
        // Header é um nome
        name = headerText;
      }
    }

    // 3. Buscar no painel lateral de info do contato (drawer)
    // Aqui fica o nome real (~João Carlos Balan) e o telefone
    const drawer = document.querySelector(
      'div[data-testid="contact-info-drawer"], ' +
      'div[data-testid="chat-info-drawer"], ' +
      'section[data-testid="contact-info"], ' +
      'div._3YS_f, div._1-lf9'
    );
    if (drawer) {
      // Buscar telefone no drawer
      const phoneSelectors = [
        'span[title*="+55"]',
        'span[title*="+"]',
        'div[data-testid="contact-info-phone"] span',
      ];
      if (!phone) {
        for (const sel of phoneSelectors) {
          const els = drawer.querySelectorAll(sel);
          for (const el of els) {
            const txt = (el.getAttribute("title") || el.textContent || "").trim();
            const digits = txt.replace(/\D/g, "");
            if (digits.length >= 10 && digits.length <= 15) {
              phone = digits;
              break;
            }
          }
          if (phone) break;
        }
      }

      // Buscar nome real no drawer (aparece como ~NomeContato ou no topo do painel)
      if (!name) {
        const allSpans = drawer.querySelectorAll("span[title], span[dir='auto']");
        for (const span of allSpans) {
          let txt = (span.getAttribute("title") || span.textContent || "").trim();
          if (!txt || txt.length > 80) continue;
          // Ignorar se for um telefone
          const digits = txt.replace(/\D/g, "");
          if (digits.length >= 10 && digits.length <= 15) continue;
          // Ignorar labels do WhatsApp
          if (txt.toLowerCase().includes("clique")) continue;
          if (txt.toLowerCase().includes("pesquisar")) continue;
          if (txt.toLowerCase().includes("recado")) continue;
          if (txt.toLowerCase().includes("mídia")) continue;
          if (txt.toLowerCase().includes("media")) continue;
          if (txt.toLowerCase().includes("link")) continue;
          if (txt.toLowerCase().includes("adicione notas")) continue;
          // Limpar prefixo ~ do WhatsApp
          txt = txt.replace(/^~\s*/, "");
          if (txt.length >= 2) {
            name = txt;
            break;
          }
        }
      }
    }

    // 4. Se ainda não achou telefone, buscar no header
    if (!phone && header) {
      const allText = header.textContent || "";
      const phoneMatch = allText.match(/\+?55\s*\d{2}\s*\d{4,5}[\s\-]?\d{4}/);
      if (phoneMatch) {
        phone = phoneMatch[0].replace(/\D/g, "");
      }
    }

    // 5. Se nome ainda não definido, usar o headerText
    if (!name && headerText) {
      name = headerText;
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

  // ==================== SALVAMENTO RÁPIDO (1 clique) ====================

  async function quickSave(pipelineId, etapaId, etapaNome, btnEl) {
    const { name, phone } = extractContactInfo();
    if (!phone) {
      showFeedback("Não consegui detectar o telefone do contato", "error");
      return;
    }

    const originalHtml = btnEl.innerHTML;
    btnEl.disabled = true;
    btnEl.innerHTML = "…";

    try {
      const body = {
        telefone: phone.replace(/\D/g, ""),
        nome: name || "Contato WhatsApp",
        notas: "",
        tags: ["whatsapp-web", "chrome-extension"],
        pipeline_id: parseInt(pipelineId),
        etapa_id: parseInt(etapaId),
      };
      const result = await apiCall("", "POST", body);
      if (!result) {
        btnEl.disabled = false;
        btnEl.innerHTML = originalHtml;
        return;
      }

      if (result.status === "created") {
        showFeedback(`${name || "Contato"} → ${result.etapa || etapaNome}`, "success");
      } else if (result.status === "existing") {
        showFeedback(result.message || "Contato já existe no CRM", "info");
      } else {
        throw new Error(result.error || "Erro desconhecido");
      }
      btnEl.innerHTML = "&#10003;";
      setTimeout(() => { btnEl.innerHTML = originalHtml; btnEl.disabled = false; }, 2500);
    } catch (err) {
      showFeedback(`Erro: ${err.message}`, "error");
      btnEl.innerHTML = originalHtml;
      btnEl.disabled = false;
    }
  }

  // ==================== DETECÇÃO DE LISTA NATIVA ====================

  // Liga logs de diagnóstico no console (DevTools) para calibrar o seletor.
  const CRM_DEBUG_LISTA = true;

  // Lê o nome da lista nativa do WhatsApp a partir do botão específico
  // (data-testid="label-chat-header-button"). Retorna [] se a conversa não
  // estiver em nenhuma lista (o botão some / fica sem nome).
  function lerListasNativas() {
    const header = document.querySelector("#main header");
    if (!header) return [];

    const botao = header.querySelector('button[data-testid="label-chat-header-button"]');
    if (!botao) {
      if (CRM_DEBUG_LISTA) console.log("[CRM Extension] Botão de lista nativo ausente → sem lista.");
      return [];
    }

    // Dentro do botão: 1 span-ícone (cor), 1 span com o NOME, 1 svg (seta).
    // Pegamos o span de texto (ignora o ícone, que não tem texto).
    let nome = "";
    botao.querySelectorAll("span").forEach((sp) => {
      const t = (sp.textContent || "").trim();
      if (t && t.length <= 40 && t.length > nome.length) nome = t;
    });

    nome = nome.replace(/^[✓✔☑\s]+/, "").trim().toLowerCase();

    if (CRM_DEBUG_LISTA) console.log("[CRM Extension] Lista nativa lida:", JSON.stringify(nome));

    // "adicionar à lista" = placeholder do botão quando NÃO há lista escolhida
    if (!nome || nome.includes("adicionar")) return [];

    return [nome];
  }

  // Retorna o slug da etapa de maior prioridade entre as listas nativas detectadas
  // (ou null se nenhuma lista mapeada estiver presente).
  function detectarEtapaPelaLista() {
    const textos = lerListasNativas();

    const encontrados = new Set();
    textos.forEach((txt) => {
      if (LISTA_PARA_ETAPA[txt]) encontrados.add(LISTA_PARA_ETAPA[txt]);
    });

    if (!encontrados.size) {
      if (CRM_DEBUG_LISTA) console.log("[CRM Extension] Nenhuma lista mapeada → NÃO envia.");
      return null;
    }

    let melhor = null;
    let melhorP = -1;
    encontrados.forEach((slug) => {
      const p = ETAPA_PRIORIDADE[slug] || 0;
      if (p > melhorP) { melhorP = p; melhor = slug; }
    });
    if (CRM_DEBUG_LISTA) console.log("[CRM Extension] Lista → etapa:", melhor, [...encontrados]);
    return melhor;
  }

  // Auto-joga a conversa atual pro CRM se ela estiver numa lista mapeada.
  async function autoSaveByLista() {
    const etapaSlug = detectarEtapaPelaLista();
    if (!etapaSlug) return;

    const { name, phone } = extractContactInfo();
    if (!phone) return;

    // Não repetir para a mesma combinação telefone+etapa nesta sessão
    const key = `${phone}:${etapaSlug}`;
    if (autoSavedKey === key) return;

    const pipeline = (pipelinesCache || []).find((p) => p.slug === QUICK_PIPELINE_SLUG);
    if (!pipeline) return;
    const etapa = (pipeline.etapas || []).find((e) => e.slug === etapaSlug);
    if (!etapa) return;

    autoSavedKey = key;
    try {
      const result = await apiCall("", "POST", {
        telefone: phone.replace(/\D/g, ""),
        nome: name || "Contato WhatsApp",
        notas: "",
        tags: ["whatsapp-web", "chrome-extension", "auto-lista"],
        pipeline_id: parseInt(pipeline.id),
        etapa_id: parseInt(etapa.id),
      });
      if (result && (result.status === "created" || result.moved)) {
        showFeedback(`${name || "Contato"} → ${result.etapa || etapa.nome} (auto)`, "success");
      }
    } catch (e) {
      console.error("[CRM Extension] auto-save lista falhou:", e);
      autoSavedKey = null; // permite tentar de novo
    }
  }

  // ==================== BOTÃO ====================

  function createButton() {
    const btn = document.createElement("button");
    btn.id = "crm-save-btn";
    btn.innerHTML = "&#128190; Salvar no CRM";
    btn.addEventListener("click", openForm);
    return btn;
  }

  // Cria os botões de atalho (1 por etapa da pipeline rápida)
  function createQuickButtons() {
    const wrap = document.createElement("span");
    wrap.id = "crm-quick-wrap";

    const pipeline = (pipelinesCache || []).find(
      (p) => p.slug === QUICK_PIPELINE_SLUG
    );
    if (!pipeline || !pipeline.etapas || !pipeline.etapas.length) {
      return wrap; // pipeline ainda não carregada / não existe
    }

    pipeline.etapas.forEach((etapa) => {
      const b = document.createElement("button");
      b.className = "crm-quick-btn";
      b.textContent = etapa.nome;
      b.title = `Salvar direto em "${etapa.nome}"`;
      b.style.setProperty("--crm-quick-color", etapa.cor || "#6366f1");
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        quickSave(pipeline.id, etapa.id, etapa.nome, b);
      });
      wrap.appendChild(b);
    });
    return wrap;
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

    // Remover atalhos antigos também
    const oldQuick = document.getElementById("crm-quick-wrap");
    if (oldQuick) oldQuick.remove();

    const btn = createButton();
    const quick = createQuickButtons();

    const actionsContainer = header.querySelector(
      'div[role="toolbar"], span[data-testid="menu"]'
    );
    if (actionsContainer) {
      actionsContainer.parentNode.insertBefore(btn, actionsContainer);
      actionsContainer.parentNode.insertBefore(quick, actionsContainer);
    } else {
      header.appendChild(btn);
      header.appendChild(quick);
    }

    // Trocou de conversa: libera novo auto-save
    autoSavedKey = null;

    // Verificar se contato já existe no CRM (dica leve no botão)
    const { phone } = extractContactInfo();
    if (phone) {
      apiCall(`check/?telefone=${phone}`, "GET").then((result) => {
        if (result && result.exists && result.pipelines && result.pipelines.length > 0) {
          const p = result.pipelines[0];
          btn.classList.add("crm-exists");
          btn.innerHTML = `&#128204; ${p.etapa || p.pipeline}`;
        }
      });
    }

    // Auto-detecta a lista nativa do WhatsApp e joga pro CRM na fase mapeada.
    // Pequeno atraso para o header (nome da lista) terminar de renderizar.
    setTimeout(autoSaveByLista, 800);
  }

  // ==================== OBSERVER ====================

  // Detecta mudança de conversa observando o nome no header — NÃO reprocessa
  // a cada mutação do footer/composer (isso interferia no microfone nativo).
  function onDomChange() {
    if (debounceTimer) return;
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      const main = document.querySelector("#main");
      if (!main) return;
      const titleEl = main.querySelector("header span[title]");
      const currentTitle = titleEl ? titleEl.getAttribute("title") : null;
      // Só reinjeta se a conversa mudou OU os botões sumiram.
      if (currentTitle !== lastHeaderText || !document.getElementById("crm-save-btn")) {
        injectButton();
      }
    }, 600);
  }

  function startObserver() {
    // Observa apenas mudanças de FILHOS diretos do #main (troca de conversa),
    // sem subtree — assim digitação, gravação de áudio e scroll do chat NÃO
    // disparam o observer e não interferem na UI nativa do WhatsApp.
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
        // DIAGNÓSTICO +20min: roda sozinho 6s após carregar (dá tempo da lista renderizar)
        setTimeout(() => {
          console.log("%c[CRM +20min] === DIAGNÓSTICO AUTOMÁTICO ===", "color:#22c55e;font-weight:bold");
          try { diagnosticarListaConversas(); } catch (e) { console.log("[CRM +20min] erro:", e); }
        }, 6000);
      }
    }, 1000);
  }

  // ==================== DIAGNÓSTICO: ESPERANDO ATENDIMENTO (+20min) ====================
  // Fase 1 (calibração): apenas LÊ e LOGA o que consegue extrair da lista de
  // conversas — não alerta nem envia nada. Use o console (F12) para ver o que
  // ele detecta e ajustar os seletores.

  // Tenta extrair, de cada linha da lista, o que precisamos:
  //   nome, horário (texto), e se a última msg parece ser do cliente (não enviada)
  function diagnosticarListaConversas() {
    // INVESTIGAÇÃO: descobrir o seletor certo testando vários candidatos.
    const candidatosPainel = [
      '#pane-side',
      'div[aria-label="Lista de conversas"]',
      'div[aria-label="Chat list"]',
      'div[aria-label="Conversas"]',
      'div[role="grid"]',
    ];
    console.log("[CRM +20min] Testando seletores de painel:");
    candidatosPainel.forEach((sel) => {
      const el = document.querySelector(sel);
      console.log(`   ${el ? "✅" : "❌"} ${sel}${el ? ` (aria-label="${el.getAttribute("aria-label")}")` : ""}`);
    });

    // Conta itens por vários seletores possíveis de linha
    console.log("[CRM +20min] Contagem de itens por seletor:");
    [
      'div[role="listitem"]',
      'div[role="row"]',
      '#pane-side div[role="listitem"]',
      '#pane-side div[role="row"]',
      'div[aria-label] div[role="listitem"]',
    ].forEach((sel) => {
      console.log(`   ${document.querySelectorAll(sel).length.toString().padStart(4)} × ${sel}`);
    });

    // Escolhe o painel que existir
    const painel = document.querySelector(candidatosPainel.join(", "));
    if (!painel) {
      console.log("[CRM +20min] ⚠️ Nenhum painel encontrado. Veja acima qual seletor deu ✅.");
      return [];
    }
    console.log(`[CRM +20min] Painel usado: ${painel.id ? "#" + painel.id : painel.getAttribute("aria-label")}`);

    // Tenta listitem; se zero, tenta row
    let linhas = painel.querySelectorAll('div[role="listitem"]');
    if (!linhas.length) linhas = painel.querySelectorAll('div[role="row"]');
    console.log(`[CRM +20min] ${linhas.length} conversas carregadas na lista.`);

    const dados = [];
    linhas.forEach((linha, i) => {
      const txt = (linha.textContent || "").trim();

      // Nome: primeiro span[title] da linha
      const nomeEl = linha.querySelector("span[title]");
      const nome = nomeEl ? (nomeEl.getAttribute("title") || "").trim() : "";

      // Horário: o WhatsApp põe a hora num elemento separado (ex: "14:12", "ontem")
      // Vamos coletar candidatos curtos que parecem hora/data.
      let horario = "";
      linha.querySelectorAll("span, div").forEach((el) => {
        const t = (el.textContent || "").trim();
        if (!t || t.length > 12) return;
        if (/^\d{1,2}:\d{2}$/.test(t) || /ontem|hoje/i.test(t) ||
            /^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(t)) {
          if (!horario) horario = t;
        }
      });

      // INVESTIGAÇÃO: capturar a PRÉVIA da última mensagem (2ª linha da conversa).
      // A prévia costuma estar num span[title] diferente do nome, ou no texto restante.
      let previa = "";
      const titles = linha.querySelectorAll("span[title]");
      if (titles.length > 1) {
        // normalmente: [0]=nome, [último]=prévia
        previa = (titles[titles.length - 1].getAttribute("title") || "").trim();
      }
      // fallback: texto da linha menos o nome e o horário
      if (!previa) {
        previa = txt.replace(nome, "").replace(horario, "").trim().slice(0, 60);
      }

      // Detectar check de "mensagem enviada por você". O ✓/✓✓ aparece como
      // data-icon perto da prévia. Capturamos todos os data-icon e checamos
      // se algum contém "check" (status-dblcheck, status-check, msg-dblcheck...).
      const iconesLinha = [];
      linha.querySelectorAll("[data-icon]").forEach((el) => iconesLinha.push(el.getAttribute("data-icon") || ""));
      const temCheck = iconesLinha.some((ic) => /check/i.test(ic));

      // "Você:" no texto/prévia também indica msg sua
      const dizVoce = /(^|\s)(você|voce|you)\s*:/i.test(previa) || /(^|\s)(você|voce|you)\s*:/i.test(txt);

      // Última do cliente = sem check E sem "Você:"
      const ultimaDoCliente = !temCheck && !dizVoce;

      // Badge de não-lidas
      const naoLidas = linha.querySelector('span[aria-label*="não lida"], span[aria-label*="unread"]');

      dados.push({
        i,
        nome: nome || "(sem nome)",
        horario: horario || "(sem horário)",
        previa,
        temCheck,
        dizVoce,
        ultimaDoCliente,
        iconesLinha,
        naoLidas: !!naoLidas,
      });
    });

    // Amostra: quem mandou a última (🟡 cliente / ⚪ você) + ícones + prévia
    console.log("[CRM +20min] Amostra (até 20) — quem | [ícones] | horário | nome → prévia:");
    dados.slice(0, 20).forEach((d) => {
      console.log(
        `  ${d.ultimaDoCliente ? "🟡 CLI" : "⚪ você"} | [${d.iconesLinha.join(",") || "—"}] | ${d.horario.padEnd(8)} | ${d.nome}  →  "${d.previa.slice(0, 45)}"`
      );
    });
    const esperando = dados.filter((d) => d.ultimaDoCliente);
    console.log(`[CRM +20min] ${esperando.length} de ${dados.length} com última msg do CLIENTE (carregadas).`);
    return dados;
  }

  // Expor no console pra você chamar manualmente: __crmDiag()
  window.__crmDiag = diagnosticarListaConversas;

  // ==================== TRIAGEM IA (arrastão) ====================
  // Lê a última mensagem COMPLETA de cada conversa da lista, manda pro backend
  // (que classifica com Sonnet) e LOGA quem precisa de atendente. Fase 1 = dry-run
  // (não marca nada como não-lida ainda).

  // Rola a lista de conversas pra baixo até carregar ~alvo conversas (ou parar
  // de crescer). O WhatsApp usa virtual scrolling — só carrega o visível.
  // Acha o elemento que REALMENTE rola (scrollHeight > clientHeight) perto da lista.
  function acharScroller() {
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (!painel) return null;
    // procura no painel e descendentes o que tem overflow vertical real
    const candidatos = [painel, ...painel.querySelectorAll("div")];
    for (const el of candidatos) {
      if (el.scrollHeight > el.clientHeight + 50) {
        const oy = getComputedStyle(el).overflowY;
        if (oy === "auto" || oy === "scroll" || oy === "overlay") return el;
      }
    }
    return painel;
  }

  // Lê o "rótulo de tempo" da conversa (canto sup. direito da linha) e classifica
  // em quantos DIAS atrás é. WhatsApp mostra: "18:12" (hoje), "Ontem",
  // dia da semana ("terça-feira" = essa semana), ou data "12/06/2026".
  // Retorna { dias, hora } — dias=0 hoje, 1 ontem, 2 anteontem...; hora só p/ hoje.
  function lerTempoLinha(linha) {
    // O timestamp fica no cell-frame-primary-detail. Em algumas versões o texto
    // está num span filho, em outras direto. Pega o 1º texto que pareça
    // hora/data/dia, varrendo todos os spans desse bloco.
    let txt = "";
    const bloco = linha.querySelector('[data-testid="cell-frame-primary-detail"]');
    if (bloco) {
      const cands = [bloco, ...bloco.querySelectorAll("span")];
      for (const el of cands) {
        const t = (el.textContent || "").trim().toLowerCase();
        if (t && /\d{1,2}:\d{2}|ontem|feira|domingo|sábado|sabado|\d{1,2}\/\d{1,2}/.test(t)) {
          txt = t; break;
        }
      }
    }
    if (!txt) return { dias: null, hora: null, txt };

    // Hoje: "18:12" / "9:05"
    const mHora = txt.match(/^(\d{1,2}):(\d{2})$/);
    if (mHora) return { dias: 0, hora: parseInt(mHora[1], 10) + parseInt(mHora[2], 10) / 60, txt };

    if (/ontem/.test(txt)) return { dias: 1, hora: null, txt };

    // Dia da semana (essa semana): calcula quantos dias atrás
    const semana = { domingo: 0, "segunda-feira": 1, "terça-feira": 2, "terca-feira": 2,
                     "quarta-feira": 3, "quinta-feira": 4, "sexta-feira": 5, sábado: 6, sabado: 6 };
    if (txt in semana) {
      const hojeDow = new Date().getDay();
      let d = hojeDow - semana[txt];
      if (d <= 0) d += 7; // dia da semana sempre no passado (1 a 6 dias atrás)
      return { dias: d, hora: null, txt };
    }

    // Data dd/mm/aaaa → calcula diferença em dias
    const mData = txt.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
    if (mData) {
      const [, dd, mm, aa] = mData;
      const ano = aa.length === 2 ? 2000 + parseInt(aa, 10) : parseInt(aa, 10);
      const dt = new Date(ano, parseInt(mm, 10) - 1, parseInt(dd, 10));
      const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
      const diff = Math.round((hoje - dt) / 86400000);
      return { dias: diff >= 0 ? diff : null, hora: null, txt };
    }
    return { dias: null, hora: null, txt };
  }

  // Extrai os dados de UMA linha. Retorna null se não der pra ler.
  function parseLinha(linha) {
      const nomeEl = linha.querySelector("span[title]");
      const nome = nomeEl ? (nomeEl.getAttribute("title") || "").trim() : "";

      // Última mensagem COMPLETA: o WhatsApp guarda o texto inteiro no
      // span[dir="ltr"] / span[dir="auto"] da prévia (descoberto via DevTools).
      let ultimaMsg = "";
      const previaSpans = linha.querySelectorAll('span[dir="ltr"], span[dir="auto"]');
      previaSpans.forEach((sp) => {
        const t = (sp.getAttribute("title") || sp.textContent || "").trim();
        // ignora nome e horários curtos; pega o maior texto (a mensagem)
        if (t && t !== nome && t.length > ultimaMsg.length) ultimaMsg = t;
      });

      // Quem mandou a última: o WhatsApp marca msg ENVIADA pela loja com o
      // ícone de status `wds-ic-read` (✓✓ lido), `wds-ic-dblcheck` (entregue)
      // ou `wds-ic-check` (enviado). Aparece como data-icon OU como <svg><title>.
      const dataIcons = [];
      linha.querySelectorAll("[data-icon]").forEach((el) => dataIcons.push(el.getAttribute("data-icon") || ""));
      linha.querySelectorAll("svg title").forEach((t) => dataIcons.push((t.textContent || "").trim()));
      const temCheck = dataIcons.some((ic) =>
        /wds-ic-(read|dblcheck|check)|status-(dblcheck|check)|msg-(read|dblcheck|check)/i.test(ic)
      );
      const dizVoce = /(^|\s)(você|voce|you)\s*:/i.test(ultimaMsg);
      // Rascunho (draft) = você digitou mas não enviou → é a loja, não o cliente.
      const ehRascunho = !!linha.querySelector('[class*="x8r4c90"]') ||
                         /^rascunho\s*:/i.test(ultimaMsg) ||
                         dataIcons.some((ic) => /draft/i.test(ic));
      const autor = (temCheck || dizVoce || ehRascunho) ? "loja" : "cliente";

      // Detecta MÍDIA (áudio/imagem/vídeo). Áudio = ic-keyboard-voice / mic;
      // a prévia costuma ser só a duração "0:09".
      const ehAudio = dataIcons.some((ic) => /voice|mic|ptt|audio/i.test(ic)) ||
                      /^\d{1,2}:\d{2}$/.test(ultimaMsg);
      const ehImagem = dataIcons.some((ic) => /image|camera|photo/i.test(ic));
      const ehVideo = dataIcons.some((ic) => /video/i.test(ic));

      // Se a última msg é mídia, descreve pra IA entender (em vez de mandar só "0:09")
      if (ehAudio && (!ultimaMsg || /^\d{1,2}:\d{2}$/.test(ultimaMsg))) {
        ultimaMsg = "[O cliente enviou um áudio]";
      } else if (ehImagem && ultimaMsg.length < 4) {
        ultimaMsg = "[O cliente enviou uma imagem]";
      } else if (ehVideo && ultimaMsg.length < 4) {
        ultimaMsg = "[O cliente enviou um vídeo]";
      }

      // Telefone: se o nome é um número (+55 ...), extrai os dígitos
      const digits = nome.replace(/\D/g, "");
      const telefone = (digits.length >= 10 && digits.length <= 13) ? digits : "";

      if (!nome || !ultimaMsg) return null;
      const tempo = lerTempoLinha(linha);
      return { nome, telefone, ultima_msg: ultimaMsg, autor, _sinais: dataIcons, _tempo: tempo };
  }

  // Decide se uma conversa cabe na janela de tempo escolhida.
  // janela = { maxDias, minDias, horas } — ver SELETOR de período.
  function dentroDaJanela(tempo, janela) {
    if (!janela) return true;
    const d = tempo ? tempo.dias : null;
    // Sem data legível: tolerante só quando o filtro começa do TOPO (sem minDias,
    // ex: Hoje, 2 dias). As conversas vêm da mais recente pra mais antiga; o
    // corte é feito por `passouJanela` ao ver data MAIS ANTIGA que o filtro.
    // Para filtros com minDias (Só ontem/Anteontem) exige data legível.
    if (d === null) return janela.minDias == null;
    if (janela.minDias != null && d < janela.minDias) return false;
    if (janela.maxDias != null && d > janela.maxDias) return false;
    // filtro de horas só vale pra HOJE (d===0) e quando o WhatsApp deu a hora
    if (janela.horas != null && d === 0 && tempo.hora != null) {
      const agora = new Date().getHours() + new Date().getMinutes() / 60;
      if (agora - tempo.hora > janela.horas) return false;
    }
    return true;
  }

  // Coleta as conversas rolando a lista e acumulando num Map (dedup por
  // nome+msg). Com virtual scroll do WhatsApp NÃO dá pra rolar e voltar ao topo
  // antes de coletar — voltar descarrega as linhas. Então coletamos DURANTE.
  // `janela` filtra por período; para de rolar ao ultrapassar maxDias.
  async function coletarComScroll(alvo = 150, janela = null) {
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (!painel) return [];
    const scroller = acharScroller();
    console.log(`[Triagem IA] scroller: ${scroller ? (scroller.id || (scroller.className || "").slice(0, 30)) : "nenhum"}`);

    const mapa = new Map(); // chave: nome|msg → conversa
    let passouJanela = false; // o RODAPÉ da lista já está todo fora da janela → parar
    const snapshot = () => {
      const linhas = [...painel.querySelectorAll('div[role="row"]')];
      let foraSeguidas = 0; // conversas mais antigas que maxDias no FINAL da lista
      linhas.forEach((linha) => {
        const c = parseLinha(linha);
        if (!c) return;
        const maisAntiga = janela && janela.maxDias != null && c._tempo &&
          c._tempo.dias != null && c._tempo.dias > janela.maxDias;
        // conta seguidas no rodapé: se aparece uma dentro da janela, zera
        foraSeguidas = maisAntiga ? foraSeguidas + 1 : 0;
        if (!dentroDaJanela(c._tempo, janela)) return; // fora do período: ignora
        const chave = `${c.nome}|${c.ultima_msg.slice(0, 40)}`;
        if (!mapa.has(chave)) mapa.set(chave, c);
      });
      // só para quando o FIM da lista carregada está claramente fora da janela
      // (>=5 seguidas) — evita corte por uma data fora de ordem no meio.
      if (foraSeguidas >= 5) passouJanela = true;
    };

    // Rola em PASSOS PEQUENOS (uma "tela" por vez). Jogar direto pro
    // scrollHeight faz o virtual-scroll do WhatsApp re-renderizar as linhas
    // FORA DE ORDEM (datas embaralhadas) e pular blocos. Passo controlado
    // = React renderiza em sequência e não pulamos conversas.
    // DIAGNÓSTICO: o que o parser leu de tempo nas primeiras linhas?
    const amostraTempo = [...painel.querySelectorAll('div[role="row"]')].slice(0, 8)
      .map((l) => { const t = lerTempoLinha(l); return `"${t.txt}"→dias=${t.dias}`; });
    console.log(`[Triagem IA] tempo lido (amostra): ${amostraTempo.join(", ")}`);

    // Dois contadores SEPARADOS: scroll travado e Map travado. Só paramos
    // quando AMBOS travam juntos (o scroll pode crescer sem revelar conversa
    // nova por timing do React, e vice-versa — não dá pra misturar).
    let scrollTravado = 0;
    let mapTravado = 0;
    let alturaAnterior = -1;
    for (let i = 0; i < 200; i++) {
      snapshot();
      if (mapa.size >= alvo) break;
      if (passouJanela) break; // já vimos conversas mais antigas que o filtro
      const antes = mapa.size;
      const topoAntes = scroller ? scroller.scrollTop : 0;
      if (scroller) {
        const passo = Math.max(300, scroller.clientHeight - 100); // ~1 tela
        scroller.scrollTop = topoAntes + passo;
      } else {
        const linhas = painel.querySelectorAll('div[role="row"]');
        if (linhas.length) linhas[linhas.length - 1].scrollIntoView({ block: "end" });
      }
      await sleep(450); // dá tempo do React renderizar o próximo bloco
      snapshot();

      // scroll cresceu de verdade?
      const cresceu = scroller ? (scroller.scrollTop - alturaAnterior > 2) : true;
      alturaAnterior = scroller ? scroller.scrollTop : alturaAnterior;
      scrollTravado = cresceu ? 0 : scrollTravado + 1;
      mapTravado = (mapa.size === antes) ? mapTravado + 1 : 0;

      // só desiste se o scroll REALMENTE chegou ao fim (8 passos travado) E
      // o Map não cresce mais. Antes parava cedo com msgs repetidas.
      if (scrollTravado >= 8 && mapTravado >= 8) break;
    }
    snapshot();
    console.log(`[Triagem IA] fim do scroll: scrollTravado=${scrollTravado}, mapTravado=${mapTravado}, coletadas=${mapa.size}`);

    // volta pro topo (UX) — robusto, várias tentativas
    const voltarTopo = () => {
      if (scroller) scroller.scrollTop = 0;
      const ps = document.querySelector('#pane-side');
      if (ps) ps.scrollTop = 0;
      const primeira = painel.querySelector('div[role="row"]');
      if (primeira) primeira.scrollIntoView({ block: "start" });
    };
    for (let k = 0; k < 4; k++) { voltarTopo(); await sleep(150); }

    // numera as conversas pra ter id estável
    return [...mapa.values()].map((c, i) => ({ id: `row-${i}`, ...c }));
  }

  async function rodarTriagemIA(btnEl, opts = {}) {
    const modoMarcar = opts.marcar || null; // null=dry-run, "teste"=1ª, "lote"=todas
    const janela = opts.janela || null;     // filtro de período (ver SELETOR)

    // Rola E coleta ao mesmo tempo (virtual scroll não deixa rolar e voltar
    // ao topo antes de coletar). Alvo ~150 conversas únicas dentro da janela.
    if (btnEl) { btnEl.disabled = true; btnEl.dataset.txt = btnEl.textContent; btnEl.textContent = "📜 Carregando…"; }
    if (janela) console.log(`[Triagem IA] janela: ${janela._label || JSON.stringify(janela)}`);
    const conversas = await coletarComScroll(150, janela);
    console.log(`%c[Triagem IA] Coletadas ${conversas.length} conversas (${janela ? janela._label : "todas"}). Enviando ao Sonnet...`, "color:#22c55e;font-weight:bold");
    if (!conversas.length) {
      const msg = janela
        ? `Nenhuma conversa em "${janela._label}". Talvez não haja mensagens nesse período.`
        : "Nenhuma conversa lida na lista";
      showFeedback(msg, "info");
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = btnEl.dataset.txt || btnEl.textContent; }
      return;
    }

    // DIAGNÓSTICO do autor: quantas viraram loja x cliente + amostra de sinais
    const loja = conversas.filter((c) => c.autor === "loja").length;
    console.log(`[Triagem IA] autor detectado: ${loja} loja / ${conversas.length - loja} cliente`);
    console.log("[Triagem IA] amostra sinais (10):");
    conversas.slice(0, 10).forEach((c) =>
      console.log(`   ${c.autor === "loja" ? "🏪" : "🟡"} ${c.nome}  sinais=[${(c._sinais || []).filter(Boolean).join(" | ")}]`)
    );
    // remove _sinais antes de enviar (não precisa ir pro backend)
    const enviar = conversas.map(({ _sinais, ...rest }) => rest);

    if (btnEl) { btnEl.disabled = true; btnEl.textContent = "🤖 Analisando…"; }

    try {
      const result = await apiCall("triagem/", "POST", { conversas: enviar });
      if (!result || !result.resultados) {
        showFeedback("Erro na triagem: " + (result && result.error || "sem resposta"), "error");
        return;
      }

      const precisam = result.resultados.filter((r) => r.precisa_humano);
      console.log(`%c[Triagem IA] ${precisam.length} de ${result.total} PRECISAM de atendente:`, "color:#ef4444;font-weight:bold");
      const ordenados = precisam
        .sort((a, b) => ({alta:0,media:1,baixa:2}[a.urgencia] - {alta:0,media:1,baixa:2}[b.urgencia]));
      ordenados.forEach((r) => console.log(`   🔴 [${(r.urgencia||"").toUpperCase()}] ${r.nome} — ${r.motivo}`));

      // SELO VISUAL: pinta a borda das conversas que precisam de atendente.
      // Mantido por observer + intervalo (o WhatsApp re-renderiza e apagaria).
      limparSelos();
      ordenados.forEach((r) => aplicarSelo(r.nome, r.urgencia));
      iniciarManutencaoSelos();
      console.log(`[Triagem IA] ${ordenados.length} selos aplicados (mantidos até o F5).`);

      // mapa id → conversa original (pra recuperar telefone)
      const porId = {};
      conversas.forEach((c) => { porId[c.id] = c; });

      if (!modoMarcar) {
        console.log("[Triagem IA] (dry-run: nada foi marcado)");
        showFeedback(`🤖 ${precisam.length} precisam de atendente (veja o console)`, precisam.length ? "info" : "success");
      } else if (modoMarcar === "crm") {
        // Joga os classificados pro CRM Kanban (pipeline Atendimento)
        console.log(`%c[Triagem IA] Enviando ${ordenados.length} pro CRM...`, "color:#6366f1;font-weight:bold");
        let ok = 0;
        for (const r of ordenados) {
          const c = porId[r.id] || {};
          const etapa = r.urgencia === "alta" ? "esperando-urgente" : "esperando-compras";
          const res = await apiCall("crm-triagem/", "POST", {
            nome: c.nome, telefone: c.telefone || "",
            etapa_slug: etapa, motivo: r.motivo, urgencia: r.urgencia,
          });
          if (res && res.status) { ok++; console.log(`   → CRM [${etapa}] ${c.nome}`); }
        }
        showFeedback(`✅ ${ok}/${ordenados.length} enviados ao CRM`, ok ? "success" : "error");
      } else {
        // Marca como não-lida: "teste" = só a 1ª; "lote" = todas
        const alvos = modoMarcar === "teste" ? ordenados.slice(0, 1) : ordenados;
        console.log(`%c[Triagem IA] Marcando ${alvos.length} como não-lida (${modoMarcar})...`, "color:#f59e0b;font-weight:bold");
        let ok = 0;
        for (const r of alvos) {
          if (await marcarNaoLida(r.nome)) ok++;
          await sleep(400);
        }
        showFeedback(`✅ ${ok}/${alvos.length} marcadas como não-lida`, ok ? "success" : "error");
      }
    } catch (e) {
      console.log("[Triagem IA] erro:", e);
      showFeedback("Erro na triagem IA", "error");
    } finally {
      if (btnEl) { btnEl.disabled = false; btnEl.textContent = btnEl.dataset.txt || "🤖 Triagem IA"; }
    }
  }

  // ==================== SELO VISUAL NA CONVERSA ====================

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Mapa persistente: nome da conversa → urgência. O WhatsApp re-renderiza a
  // lista constantemente e apaga nossas classes; por isso guardamos quem precisa
  // de selo e RE-APLICAMOS continuamente (observer + intervalo).
  const selosAtivos = new Map(); // nome → "alta" | "media"
  let seloObserver = null;
  let seloInterval = null;

  function _pintarLinha(linha, urgencia) {
    const classe = urgencia === "alta" ? "crm-selo-urgente" : "crm-selo-espera";
    if (!linha.classList.contains(classe)) {
      linha.classList.remove("crm-selo-urgente", "crm-selo-espera");
      linha.classList.add(classe);
    }
  }

  // Varre a lista e aplica os selos que estão no mapa (chamado repetidamente)
  function reaplicarSelos() {
    if (!selosAtivos.size) return;
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (!painel) return;
    painel.querySelectorAll('div[role="row"]').forEach((linha) => {
      const el = linha.querySelector("span[title]");
      const nome = el ? (el.getAttribute("title") || "").trim() : "";
      if (nome && selosAtivos.has(nome)) {
        _pintarLinha(linha, selosAtivos.get(nome));
      }
    });
  }

  // Registra um selo no mapa (será mantido pelo observer/intervalo)
  function aplicarSelo(nome, urgencia) {
    selosAtivos.set(nome, urgencia);
    return true;
  }

  // Inicia a manutenção dos selos: observer no painel + reforço a cada 1.5s
  function iniciarManutencaoSelos() {
    reaplicarSelos();
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (painel && !seloObserver) {
      seloObserver = new MutationObserver(() => reaplicarSelos());
      seloObserver.observe(painel, { childList: true, subtree: true });
    }
    if (!seloInterval) {
      seloInterval = setInterval(reaplicarSelos, 1500);
    }
  }

  // Limpa todos os selos (ex: antes de reaplicar) — esvazia o mapa e tira classes
  function limparSelos() {
    selosAtivos.clear();
    document.querySelectorAll(".crm-selo-urgente, .crm-selo-espera").forEach((el) => {
      el.classList.remove("crm-selo-urgente", "crm-selo-espera");
    });
  }

  // Acha a linha da conversa pelo nome exibido na lista.
  function acharLinhaPorNome(nome) {
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (!painel) return null;
    const linhas = painel.querySelectorAll('div[role="row"]');
    for (const linha of linhas) {
      const el = linha.querySelector("span[title]");
      if (el && (el.getAttribute("title") || "").trim() === nome) return linha;
    }
    return null;
  }

  // Marca UMA conversa (pelo nome) como não-lida, automatizando os cliques:
  // hover na linha → botão ▾ (context-btn) → item "Marcar como não lida".
  async function marcarNaoLida(nome) {
    const linha = acharLinhaPorNome(nome);
    if (!linha) { console.log(`[Não-lida] linha não encontrada: ${nome}`); return false; }

    // 1. hover pra revelar o botão de contexto (WhatsApp só renderiza no hover).
    // Disparamos a sequência completa de eventos de ponteiro na linha e num filho.
    const alvoHover = linha.querySelector("div") || linha;
    ["pointerenter", "mouseenter", "pointerover", "mouseover", "mousemove"].forEach((tipo) => {
      alvoHover.dispatchEvent(new MouseEvent(tipo, { bubbles: true, cancelable: true, view: window }));
      linha.dispatchEvent(new MouseEvent(tipo, { bubbles: true, cancelable: true, view: window }));
    });
    await sleep(400);

    // 2. achar o botão ▾ (context-btn). Tenta vários seletores.
    let ctxBtn = linha.querySelector(
      'button[data-testid="context-btn"], [data-icon="ic-expand-more"], [aria-label*="contexto" i], [aria-label*="menu" i]'
    );
    // fallback: qualquer botão dentro da linha que tenha o svg ic-expand-more
    if (!ctxBtn) {
      linha.querySelectorAll("button, [role='button']").forEach((b) => {
        if (!ctxBtn && b.querySelector('svg title')) {
          const t = (b.querySelector('svg title').textContent || "").toLowerCase();
          if (/expand-more|chevron|arrow-down|drop-down/.test(t)) ctxBtn = b;
        }
      });
    }
    if (!ctxBtn) {
      // DIAGNÓSTICO: lista os botões/títulos da linha pra calibrar
      const btns = [];
      linha.querySelectorAll("button, [role='button']").forEach((b) => {
        const al = b.getAttribute("aria-label") || "";
        const tid = b.getAttribute("data-testid") || "";
        const svgt = b.querySelector("svg title")?.textContent || "";
        btns.push(`{aria:"${al}" testid:"${tid}" svg:"${svgt}"}`);
      });
      console.log(`[Não-lida] botão de contexto não achado: ${nome}. Botões na linha:`, btns);
      return false;
    }
    ctxBtn.click();
    await sleep(350);

    // 3. clicar em "Marcar como não lida" no menu que abriu
    const itens = document.querySelectorAll('div[role="application"] button[role="menuitem"], [role="menu"] button, button[aria-label]');
    let alvo = null;
    itens.forEach((b) => {
      const al = (b.getAttribute("aria-label") || b.textContent || "").trim().toLowerCase();
      if (/marcar como n[ãa]o lida/.test(al)) alvo = b;
    });
    if (!alvo) {
      console.log(`[Não-lida] item 'Marcar como não lida' não achado: ${nome}`);
      // fecha o menu pra não travar
      document.body.click();
      return false;
    }
    alvo.click();
    await sleep(200);
    console.log(`[Não-lida] ✅ marcada: ${nome}`);
    return true;
  }

  // Janelas de período disponíveis no seletor. dias=0 hoje, 1 ontem, ...
  // maxDias/minDias delimitam; horas filtra dentro de hoje.
  const PERIODOS = [
    { _label: "Tudo (150)",          valor: "tudo",      janela: null },
    { _label: "Hoje",               valor: "hoje",      janela: { maxDias: 0, _label: "hoje" } },
    { _label: "Hoje (últimas Xh)",   valor: "horas",     janela: { maxDias: 0, horas: 6, _label: "hoje X h" } },
    { _label: "Hoje + ontem",        valor: "2dias",     janela: { maxDias: 1, _label: "hoje+ontem" } },
    { _label: "Só ontem",           valor: "ontem",     janela: { minDias: 1, maxDias: 1, _label: "ontem" } },
    { _label: "Ontem + anteontem",   valor: "ontemante", janela: { minDias: 1, maxDias: 2, _label: "ontem+anteontem" } },
    { _label: "Só anteontem",        valor: "antes",     janela: { minDias: 2, maxDias: 2, _label: "anteontem" } },
    { _label: "Últimos 3 dias",      valor: "3dias",     janela: { maxDias: 2, _label: "hoje+2 dias" } },
  ];

  // Resolve a janela escolhida no dropdown (com horas custom se aplicável).
  function janelaSelecionada() {
    const sel = document.getElementById("crm-periodo-sel");
    const p = PERIODOS.find((x) => x.valor === (sel ? sel.value : "tudo")) || PERIODOS[0];
    if (!p.janela) return null;
    const janela = { ...p.janela };
    if (p.valor === "horas") {
      const inp = document.getElementById("crm-periodo-horas");
      const h = inp ? parseFloat(inp.value) : 6;
      janela.horas = (h > 0 && h <= 24) ? h : 6;
      janela._label = `hoje últimas ${janela.horas}h`;
    }
    return janela;
  }

  // Injeta o seletor de período + botões flutuantes (canto inferior esquerdo)
  function injectBotaoTriagem() {
    if (document.getElementById("crm-triagem-btn")) return;

    // Seletor de PERÍODO (dropdown + campo de horas opcional)
    const periodoWrap = document.createElement("div");
    periodoWrap.id = "crm-periodo-wrap";
    const sel = document.createElement("select");
    sel.id = "crm-periodo-sel";
    sel.title = "Período das conversas a analisar";
    PERIODOS.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.valor; o.textContent = p._label;
      sel.appendChild(o);
    });
    const horasInp = document.createElement("input");
    horasInp.id = "crm-periodo-horas";
    horasInp.type = "number"; horasInp.min = "1"; horasInp.max = "24";
    horasInp.value = "6"; horasInp.title = "Quantas horas atrás (só vale p/ hoje)";
    horasInp.style.display = "none";
    sel.addEventListener("change", () => {
      horasInp.style.display = sel.value === "horas" ? "inline-block" : "none";
    });
    periodoWrap.appendChild(sel);
    periodoWrap.appendChild(horasInp);
    document.body.appendChild(periodoWrap);

    const btn = document.createElement("button");
    btn.id = "crm-triagem-btn";
    btn.textContent = "🤖 Triagem IA";
    btn.title = "Analisar conversas do período com IA e listar quem precisa de atendente";
    btn.addEventListener("click", () => rodarTriagemIA(btn, { janela: janelaSelecionada() }));
    document.body.appendChild(btn);

    // Botão: joga os classificados pro CRM Kanban (pipeline Atendimento) — confiável
    const btnCrm = document.createElement("button");
    btnCrm.id = "crm-triagem-crm-btn";
    btnCrm.textContent = "📋 Triagem → CRM";
    btnCrm.title = "Analisa com IA e joga quem precisa de atendente pro CRM Kanban";
    btnCrm.addEventListener("click", () => rodarTriagemIA(btnCrm, { marcar: "crm", janela: janelaSelecionada() }));
    document.body.appendChild(btnCrm);

    // Botão de TESTE: marca só a 1ª conversa que a IA apontou (valida o auto-clique)
    const btnTest = document.createElement("button");
    btnTest.id = "crm-marcar-test-btn";
    btnTest.textContent = "🧪 Testar marcar (1)";
    btnTest.title = "Marca como não-lida APENAS a 1ª conversa que precisa de atendente (teste)";
    btnTest.addEventListener("click", () => rodarTriagemIA(btnTest, { marcar: "teste", janela: janelaSelecionada() }));
    document.body.appendChild(btnTest);
  }

  // Tenta injetar o botão depois que a UI carrega
  setTimeout(injectBotaoTriagem, 5000);
  window.__crmTriagem = rodarTriagemIA;

  // ==================== COPILOTO IA (sugestão de resposta) ====================
  // Abre a conversa, lê as últimas mensagens do DOM, pede sugestão ao backend
  // (Claude) e mostra num painel lateral. HUMANO revisa e envia — o Copiloto
  // NUNCA envia sozinho (segurança + termos do WhatsApp).

  // Clique "de verdade": o WhatsApp Web é React e ignora .click() sintético.
  // A sequência completa de eventos de mouse resolve.
  function cliqueReal(el) {
    if (!el) return false;
    const alvo = el.querySelector("div") || el;
    const rect = alvo.getBoundingClientRect();
    const opts = {
      bubbles: true, cancelable: true, view: window,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      button: 0,
    };
    ["mousedown", "mouseup", "click"].forEach((tipo) =>
      alvo.dispatchEvent(new MouseEvent(tipo, opts))
    );
    return true;
  }

  // Linhas da sidebar com bolinha de não-lida (apenas as visíveis/carregadas)
  function listarNaoLidas() {
    const painel = document.querySelector('#pane-side, div[aria-label="Lista de conversas"]');
    if (!painel) return [];
    return [...painel.querySelectorAll('div[role="row"], div[role="listitem"]')]
      .filter((l) => l.querySelector('span[aria-label*="não lida"], span[aria-label*="unread"]'));
  }

  // Lê as mensagens da conversa ABERTA (#main). Retorna [{autor, texto}] cronológico.
  function lerConversaAberta(maxMsgs = 20) {
    const main = document.querySelector("#main");
    if (!main) return { nome: "", mensagens: [] };

    const nomeEl = main.querySelector("header span[title]");
    const nome = nomeEl ? (nomeEl.getAttribute("title") || nomeEl.textContent || "").trim() : "";

    const bolhas = [...main.querySelectorAll("div.message-in, div.message-out")];
    const mensagens = [];
    bolhas.slice(-maxMsgs).forEach((b) => {
      const autor = b.classList.contains("message-in") ? "cliente" : "loja";
      let texto = "";
      const txtEl = b.querySelector("span.selectable-text, div.selectable-text");
      if (txtEl) texto = (txtEl.textContent || "").trim();
      if (!texto) {
        // mídia sem texto: marca pro modelo saber que existe algo não-textual
        if (b.querySelector('span[data-icon="audio-play"], button[aria-label*="udio"]')) {
          texto = "[O cliente enviou um áudio]";
        } else if (b.querySelector('img[src^="blob:"], img[data-testid="image-thumb"]')) {
          texto = "[O cliente enviou uma imagem]";
        } else if (b.querySelector('span[data-icon="video-pip"], video')) {
          texto = "[O cliente enviou um vídeo]";
        }
        if (texto && autor === "loja") texto = texto.replace("O cliente enviou", "A loja enviou");
      }
      if (texto) mensagens.push({ autor, texto });
    });
    return { nome, mensagens };
  }

  // Insere texto no campo de digitação (contenteditable do React)
  function inserirNoComposer(texto) {
    const box = document.querySelector('footer div[contenteditable="true"]');
    if (!box) return false;
    box.focus();
    // seleciona tudo que já tem e substitui (evita colar duplicado)
    document.execCommand("selectAll", false, null);
    document.execCommand("insertText", false, texto);
    return true;
  }

  // Painel lateral com a sugestão
  function mostrarPainelCopiloto({ nome, resposta, confianca, observacao, restantes, onProxima }) {
    fecharPainelCopiloto();
    const cores = { alta: "#22c55e", media: "#f59e0b", baixa: "#ef4444" };
    const painel = document.createElement("div");
    painel.id = "crm-copiloto-painel";
    painel.style.cssText =
      "position:fixed;top:70px;right:16px;width:330px;max-height:75vh;overflow-y:auto;" +
      "background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);" +
      "z-index:99999;font-family:inherit;padding:16px;font-size:13.5px;color:#111b21;";
    painel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
        <span style="font-size:20px;">🧠</span>
        <strong style="flex:1;">Sugestão — ${escapeHtmlCopiloto(nome || "conversa")}</strong>
        <button id="crm-cop-fechar" style="background:none;border:none;font-size:16px;cursor:pointer;color:#667781;">✕</button>
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
        <span style="background:${cores[confianca] || "#667781"};color:#fff;font-size:11px;padding:2px 8px;border-radius:10px;">confiança ${confianca}</span>
        ${restantes != null ? `<span style="font-size:11px;color:#667781;">${restantes} não lida(s) restante(s)</span>` : ""}
      </div>
      <div id="crm-cop-texto" style="background:#f0f2f5;border-radius:8px;padding:10px;white-space:pre-wrap;line-height:1.45;margin-bottom:8px;">${escapeHtmlCopiloto(resposta)}</div>
      ${observacao ? `<div style="background:#fff3cd;color:#6c4a00;border-radius:8px;padding:8px;font-size:12px;margin-bottom:8px;">⚠️ ${escapeHtmlCopiloto(observacao)}</div>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button id="crm-cop-inserir" style="flex:1;background:#00a884;color:#fff;border:none;border-radius:8px;padding:10px;font-weight:600;cursor:pointer;">✏️ Inserir no campo</button>
        <button id="crm-cop-copiar" style="background:#e9edef;color:#54656f;border:none;border-radius:8px;padding:10px 12px;cursor:pointer;">📋</button>
        ${onProxima ? `<button id="crm-cop-proxima" style="width:100%;background:#075E54;color:#fff;border:none;border-radius:8px;padding:10px;font-weight:600;cursor:pointer;">⏭ Próxima não lida</button>` : ""}
      </div>
      <div style="font-size:10.5px;color:#8696a0;margin-top:8px;">Revise antes de enviar — o Copiloto nunca envia sozinho.</div>
    `;
    document.body.appendChild(painel);
    document.getElementById("crm-cop-fechar").addEventListener("click", fecharPainelCopiloto);
    document.getElementById("crm-cop-copiar").addEventListener("click", () => {
      navigator.clipboard.writeText(resposta);
      showFeedback("Sugestão copiada 📋", "success");
    });
    document.getElementById("crm-cop-inserir").addEventListener("click", () => {
      if (inserirNoComposer(resposta)) showFeedback("Inserido — revise e envie ✏️", "success");
      else showFeedback("Não achei o campo de digitação", "error");
    });
    if (onProxima) {
      document.getElementById("crm-cop-proxima").addEventListener("click", () => {
        fecharPainelCopiloto();
        onProxima();
      });
    }
  }
  function fecharPainelCopiloto() {
    const p = document.getElementById("crm-copiloto-painel");
    if (p) p.remove();
  }
  function escapeHtmlCopiloto(s) {
    return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Sugere resposta pra conversa ABERTA
  async function sugerirConversaAtual(extra = {}) {
    const { nome, mensagens } = lerConversaAberta();
    if (!mensagens.length) {
      showFeedback("Abra uma conversa com mensagens primeiro", "error");
      return false;
    }
    showFeedback("🧠 Pensando na resposta…", "info");
    const res = await apiCall("sugerir/", "POST", { nome, mensagens });
    if (!res || res.error) {
      showFeedback("Erro na sugestão: " + ((res && res.error) || "sem resposta"), "error");
      return false;
    }
    mostrarPainelCopiloto({
      nome,
      resposta: res.resposta,
      confianca: res.confianca || "media",
      observacao: res.observacao || "",
      ...extra,
    });
    return true;
  }

  // Modo arrastão: abre as NÃO LIDAS uma a uma, no ritmo do atendente
  async function copilotoNaoLidas() {
    const fila = listarNaoLidas();
    if (!fila.length) {
      showFeedback("Nenhuma conversa não lida visível 🎉", "success");
      return;
    }
    let i = 0;
    const proxima = async () => {
      if (i >= fila.length) {
        showFeedback("Copiloto: fila de não lidas concluída ✅", "success");
        return;
      }
      const linha = fila[i++];
      cliqueReal(linha);
      await sleep(1400); // React renderizar a conversa
      const ok = await sugerirConversaAtual({
        restantes: fila.length - i,
        onProxima: proxima,
      });
      if (!ok) await proxima(); // conversa vazia/erro → segue a fila
    };
    await proxima();
  }

  function injectBotoesCopiloto() {
    if (document.getElementById("crm-copiloto-btn")) return;
    const base = "position:fixed;right:16px;z-index:99998;border:none;border-radius:24px;" +
      "padding:10px 16px;font-weight:600;font-size:13px;cursor:pointer;" +
      "box-shadow:0 4px 14px rgba(0,0,0,.25);color:#fff;";
    const btn1 = document.createElement("button");
    btn1.id = "crm-copiloto-btn";
    btn1.textContent = "🧠 Sugerir resposta";
    btn1.title = "Lê a conversa aberta e sugere a resposta (você revisa e envia)";
    btn1.style.cssText = base + "bottom:76px;background:#00a884;";
    btn1.addEventListener("click", () => sugerirConversaAtual());
    document.body.appendChild(btn1);

    const btn2 = document.createElement("button");
    btn2.id = "crm-copiloto-fila-btn";
    btn2.textContent = "🧠 Copiloto não lidas";
    btn2.title = "Abre as conversas não lidas uma a uma com sugestão de resposta";
    btn2.style.cssText = base + "bottom:24px;background:#075E54;";
    btn2.addEventListener("click", copilotoNaoLidas);
    document.body.appendChild(btn2);
  }
  setTimeout(injectBotoesCopiloto, 5000);

  // ==================== COPILOTO AUTOMÁTICO (tempo real) ====================
  // Liga o modo Auto e a IA passa a REAGIR sozinha: você clica numa conversa
  // (ou chega mensagem nova com o chat aberto) → ela lê e sugere. Sem botão.
  // Debounce + assinatura da conversa evitam chamadas repetidas (custo).
  let autoLigado = false;
  let autoTimer = null;
  let autoUltimaAssinatura = "";
  let autoPensando = false;

  function assinaturaConversa() {
    const { nome, mensagens } = lerConversaAberta(6);
    if (!mensagens.length) return "";
    const ult = mensagens[mensagens.length - 1];
    return `${nome}|${mensagens.length}|${(ult.autor + ult.texto).slice(0, 90)}`;
  }

  function agendarAutoSugestao() {
    if (!autoLigado || autoPensando) return;
    clearTimeout(autoTimer);
    autoTimer = setTimeout(async () => {
      if (!autoLigado || autoPensando) return;
      const { mensagens } = lerConversaAberta();
      if (!mensagens.length) return;
      const ult = mensagens[mensagens.length - 1];
      if (ult.autor !== "cliente") return; // só sugere quando o CLIENTE falou por último
      const assin = assinaturaConversa();
      if (!assin || assin === autoUltimaAssinatura) return; // nada mudou → não gasta IA
      autoUltimaAssinatura = assin;
      autoPensando = true;
      try {
        await sugerirConversaAtual();
      } finally {
        autoPensando = false;
      }
    }, 1000); // espera a conversa terminar de renderizar
  }

  function iniciarObserverAuto() {
    const app = document.querySelector("#app");
    if (!app) {
      setTimeout(iniciarObserverAuto, 3000);
      return;
    }
    const obs = new MutationObserver(agendarAutoSugestao);
    obs.observe(app, { childList: true, subtree: true });
    console.log("[Copiloto] Observer do modo automático ativo");
  }

  function injectBotaoAuto() {
    if (document.getElementById("crm-copiloto-auto-btn")) return;
    const btn = document.createElement("button");
    btn.id = "crm-copiloto-auto-btn";
    btn.title = "Modo automático: ao abrir uma conversa (ou chegar msg nova), a IA lê e sugere sozinha";
    const pintar = () => {
      btn.textContent = autoLigado ? "⚡ Auto: LIGADO" : "⚡ Auto: desligado";
      btn.style.cssText =
        "position:fixed;right:16px;bottom:128px;z-index:99998;border:none;border-radius:24px;" +
        "padding:10px 16px;font-weight:600;font-size:13px;cursor:pointer;color:#fff;" +
        "box-shadow:0 4px 14px rgba(0,0,0,.25);" +
        (autoLigado ? "background:#f59e0b;" : "background:#54656f;");
    };
    pintar();
    btn.addEventListener("click", () => {
      autoLigado = !autoLigado;
      autoUltimaAssinatura = ""; // re-sugere a conversa atual ao ligar
      pintar();
      showFeedback(autoLigado
        ? "⚡ Copiloto automático LIGADO — clique numa conversa e aguarde"
        : "Copiloto automático desligado", "info");
      if (autoLigado) agendarAutoSugestao();
    });
    document.body.appendChild(btn);
  }
  setTimeout(injectBotaoAuto, 5000);
  setTimeout(iniciarObserverAuto, 6000);

  window.__crmCopiloto = { sugerirConversaAtual, copilotoNaoLidas, lerConversaAberta, cliqueReal };

  waitForWhatsApp();
})();
