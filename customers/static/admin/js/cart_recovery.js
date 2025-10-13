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

function openWhatsApp(phone, cartId) {
    // Prevenir comportamento padrão
    event.preventDefault();
    event.stopPropagation();
    
    // Salvar posição do scroll
    const scrollPos = window.scrollY || window.pageYOffset;
    
    const mensagem = encodeURIComponent(
        "Olá, tudo bem ? 👋\n\n" +
        "Sou aqui da TARRAGONA CALÇADOS.\n" +
        "Verificamos que entrou em nosso site e acabou não finalizando a compra..\n" +
        "Gostaria de saber se ficou com alguma duvida sobre o site, algum modelo, ou como finalizar.\n" +
        "Os clientes que compram aqui no ATACADO vendem entre 450 a 700, hoje somos a maior empresa ref a custo beneficio do brasil com fabricação direta.\n" +
        "Estou a disposição para sanar todas as suas duvidas e te ajudar. 🛒"
    );
    
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