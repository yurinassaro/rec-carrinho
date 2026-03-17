(function() {
  'use strict';
  if (document.getElementById('crm-nav-btn')) return;

  function inject() {
    // Tentar inserir no usertools (área do "Bem-vindo, user" no topo)
    var usertools = document.getElementById('user-tools');
    if (!usertools) return;

    var btn = document.createElement('a');
    btn.id = 'crm-nav-btn';
    btn.href = '/crm/';
    btn.textContent = 'CRM';
    btn.style.cssText = 'background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff!important;padding:6px 18px;border-radius:6px;text-decoration:none;font-weight:700;font-size:12px;margin-right:10px;display:inline-block;letter-spacing:.5px;vertical-align:middle;transition:all .2s;';

    btn.onmouseenter = function() {
      btn.style.background = 'linear-gradient(135deg,#818cf8,#a78bfa)';
      btn.style.boxShadow = '0 4px 12px rgba(99,102,241,0.4)';
    };
    btn.onmouseleave = function() {
      btn.style.background = 'linear-gradient(135deg,#6366f1,#818cf8)';
      btn.style.boxShadow = 'none';
    };

    usertools.insertBefore(btn, usertools.firstChild);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
