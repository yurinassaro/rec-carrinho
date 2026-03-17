(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        // === Status dropdown change ===
        document.querySelectorAll('.lead-atacado-status').forEach(function(select) {
            select.addEventListener('change', function() {
                var leadId = this.dataset.id;
                var newStatus = this.value;
                var el = this;
                var colors = {
                    'novo': '#2196F3', 'contactado': '#FF9800',
                    'negociando': '#9C27B0', 'convertido': '#4CAF50', 'perdido': '#f44336'
                };

                fetch('/admin/customers/leadatacado/alterar-status/' + leadId + '/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                                       document.cookie.match(/csrftoken=([^;]+)/)?.[1] || ''
                    },
                    body: JSON.stringify({status: newStatus})
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) {
                        el.style.background = colors[newStatus] || '#666';
                    } else {
                        alert('Erro: ' + (data.error || 'Desconhecido'));
                    }
                })
                .catch(function(err) {
                    alert('Erro de conexão: ' + err);
                });
            });
        });

        // === WhatsApp button click ===
        document.querySelectorAll('.send-wapi-atacado').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                var leadId = this.dataset.id;

                if (!confirm('Enviar WhatsApp para este lead?')) return;

                var el = this;
                el.textContent = 'Enviando...';
                el.style.background = '#999';

                fetch('/admin/customers/leadatacado/enviar-whatsapp/' + leadId + '/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                                       document.cookie.match(/csrftoken=([^;]+)/)?.[1] || ''
                    },
                    body: 'canal=wapi'
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.success) {
                        el.textContent = 'Enviado!';
                        el.style.background = '#4CAF50';
                    } else {
                        el.textContent = 'Erro';
                        el.style.background = '#f44336';
                        alert('Erro: ' + (data.error || 'Desconhecido'));
                        setTimeout(function() {
                            el.textContent = 'WhatsApp';
                            el.style.background = '#25D366';
                        }, 3000);
                    }
                })
                .catch(function(err) {
                    el.textContent = 'WhatsApp';
                    el.style.background = '#25D366';
                    alert('Erro: ' + err);
                });
            });
        });
    });
})();
