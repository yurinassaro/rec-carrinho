function toggleRecovery(cartId, type, newStatus) {
    // Salvar posição atual do scroll
    const scrollPos = window.scrollY || window.pageYOffset;
    
    const csrfToken = getCookie('csrftoken');
    
    fetch('/admin/customers/cart/toggle-recovery/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            cart_id: cartId,
            type: type,
            status: newStatus
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Recarregar mantendo a posição
            sessionStorage.setItem('scrollPos', scrollPos);
            location.reload();
        }
    });
}

function markCartWhatsApp(cartId) {
    // Marcar WhatsApp como enviado quando clicar no link (fallback desktop)
    const csrfToken = getCookie('csrftoken');

    fetch('/admin/customers/cart/toggle-recovery/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            cart_id: cartId,
            type: 'whatsapp',
            status: true
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateWhatsAppButton(cartId);
        }
    });

    // Não prevenir o comportamento padrão do link
    return true;
}

function sendCartWhatsApp(cartId, e) {
    // Enviar WhatsApp via W-API
    const csrfToken = getCookie('csrftoken');
    const btn = (e || window.event).target.closest('button');

    // Feedback visual: loading
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳';
    btn.disabled = true;
    btn.style.opacity = '0.6';

    fetch('/admin/customers/cart/send-cart-whatsapp/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            cart_id: cartId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            btn.innerHTML = '✅';
            btn.style.background = '#25D366';
            btn.style.opacity = '1';
            updateWhatsAppButton(cartId);

            // Recarregar após 1s para atualizar estado
            setTimeout(() => {
                sessionStorage.setItem('scrollPos', window.scrollY || window.pageYOffset);
                location.reload();
            }, 1000);
        } else {
            btn.innerHTML = '❌';
            btn.style.background = '#f44336';
            btn.style.opacity = '1';
            btn.disabled = false;
            alert('Erro ao enviar WhatsApp: ' + (data.error || 'Erro desconhecido'));

            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.style.background = '#25D366';
            }, 3000);
        }
    })
    .catch(error => {
        console.error('Erro:', error);
        btn.innerHTML = '❌';
        btn.style.background = '#f44336';
        btn.style.opacity = '1';
        btn.disabled = false;
        alert('Erro de conexão ao enviar WhatsApp');

        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.style.background = '#25D366';
        }, 3000);
    });
}

function updateWhatsAppButton(cartId) {
    // Encontrar a linha do botão
    const buttons = document.querySelectorAll(`button[onclick*="toggleRecovery(${cartId}, 'whatsapp'"]`);
    
    buttons.forEach(button => {
        button.style.background = '#25D366';
        button.innerHTML = '<div>✅ WhatsApp Enviado</div><small style="opacity: 0.8;">' + 
                          new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'}) + 
                          '</small>';
        button.setAttribute('onclick', `toggleRecovery(${cartId}, 'whatsapp', false)`);
    });
}

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

// Restaurar posição do scroll após recarregar
window.addEventListener('load', function() {
    const scrollPos = sessionStorage.getItem('scrollPos');
    if (scrollPos) {
        window.scrollTo(0, parseInt(scrollPos));
        sessionStorage.removeItem('scrollPos');
    }
});

// Event listeners para dropdowns de status dos carrinhos
document.addEventListener('DOMContentLoaded', function() {
    // Selecionar todos os dropdowns de status
    const statusSelects = document.querySelectorAll('.cart-status-select');

    statusSelects.forEach(function(select) {
        select.addEventListener('change', function() {
            const cartId = this.getAttribute('data-cart-id');
            const newStatus = this.value;
            const csrfToken = getCookie('csrftoken');

            // Desabilitar o select durante a requisição
            this.disabled = true;

            fetch('/admin/customers/cart/update-cart-status/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    cart_id: cartId,
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
                alert('Erro ao atualizar status do carrinho');
                this.disabled = false;
            });
        });
    });
});