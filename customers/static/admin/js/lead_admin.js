// lead_admin.js - Gerenciamento de Leads

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function toggleLeadWhatsApp(leadId, newStatus) {
    const csrfToken = getCookie('csrftoken');

    fetch('/admin/customers/lead/toggle-lead-whatsapp/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            lead_id: leadId,
            status: newStatus
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Recarregar a página para atualizar o status
            location.reload();
        } else {
            alert('Erro ao atualizar status: ' + (data.error || 'Desconhecido'));
        }
    })
    .catch(error => {
        console.error('Erro:', error);
        alert('Erro ao atualizar status do WhatsApp');
    });
}

// Adicionar event listeners para os dropdowns de status
document.addEventListener('DOMContentLoaded', function() {
    // Selecionar todos os dropdowns de status
    const statusSelects = document.querySelectorAll('.lead-status-select');

    statusSelects.forEach(function(select) {
        select.addEventListener('change', function() {
            const leadId = this.getAttribute('data-lead-id');
            const newStatus = this.value;
            const csrfToken = getCookie('csrftoken');

            // Desabilitar o select durante a requisição
            this.disabled = true;

            fetch('/admin/customers/lead/update-lead-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    lead_id: leadId,
                    status: newStatus
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Atualizar a cor do select
                    this.style.background = data.color;
                    this.disabled = false;

                    // Mostrar mensagem de sucesso discreta
                    const successMsg = document.createElement('span');
                    successMsg.textContent = '✓';
                    successMsg.style.cssText = 'color: #4CAF50; margin-left: 5px; font-weight: bold;';
                    this.parentNode.appendChild(successMsg);

                    setTimeout(() => successMsg.remove(), 2000);
                } else {
                    alert('Erro ao atualizar status: ' + (data.error || 'Desconhecido'));
                    this.disabled = false;
                }
            })
            .catch(error => {
                console.error('Erro:', error);
                alert('Erro ao atualizar status do lead');
                this.disabled = false;
            });
        });
    });
});
