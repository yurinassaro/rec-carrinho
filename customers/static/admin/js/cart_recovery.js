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

function openWhatsApp(phone, cartId, nome, msgTemplate) {
    // Prevenir comportamento padrão
    event.preventDefault();
    event.stopPropagation();

    // Salvar posição do scroll
    const scrollPos = window.scrollY || window.pageYOffset;

    // Usar template configurado ou mensagem padrão
    const msgText = (msgTemplate || 'Olá {nome}, tudo bem ??').replace('{nome}', nome);
    const mensagem = encodeURIComponent(msgText);
    
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
            // Atualizar botão sem recarregar
            updateWhatsAppButton(cartId);
            
            // Manter posição do scroll
            window.scrollTo(0, scrollPos);
            
            // Abrir WhatsApp
            const whatsappDesktop = `whatsapp://send?phone=${phone}&text=${mensagem}`;
            window.location.href = whatsappDesktop;
            
            // Fallback para WhatsApp Web após 2 segundos
            // setTimeout(() => {
            //     if (!document.hidden) {
            //         if (confirm('WhatsApp Desktop não encontrado.\n\nDeseja abrir o WhatsApp Web?')) {
            //             window.open(`https://web.whatsapp.com/send?phone=${phone}&text=${mensagem}`, '_blank');
            //         }
            //     }
            // }, 2000);
        }
    });
    
    return false; // Prevenir qualquer ação padrão
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